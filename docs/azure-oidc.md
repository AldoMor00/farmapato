# OIDC: cómo se autentica GitHub Actions contra Azure

La landing zone en ADLS Gen2 no tiene llave: el storage account se creó con `--allow-shared-key-access false`, así que el acceso sólo se otorga por RBAC a una identidad. En local esa identidad es la del `az login`. En CI no hay usuario, y la respuesta **no** es un client secret guardado en GitHub: es una credencial federada.

Este documento cubre la autenticación. Qué recursos tiene el proyecto en Azure y el presupuesto que los vigila están en [`azure-costos.md`](azure-costos.md).

## Qué gana el proyecto con esto

Un client secret es una credencial de larga vida que hay que rotar a mano y que, filtrada, sirve hasta que alguien la revoque. Con OIDC no existe ese dato. La confianza es una **relación declarada** entre GitHub y Entra ID, y lo que viaja es un token que caduca en una hora.

```
1. El runner le pide a GitHub un JWT.
   GitHub lo firma y le mete quién corre qué:
   subject = repo:<owner>@<ownerId>/<repo>@<repoId>:ref:refs/heads/main

2. azure/login presenta ese JWT a Entra ID.
   Entra valida tres cosas contra la federated credential:
   issuer (que venga de GitHub), subject (repo y rama exactos)
   y audience (api://AzureADTokenExchange).

3. Entra devuelve un token de Azure de una hora,
   con los permisos RBAC de la managed identity.
```

El **subject es la frontera de seguridad**. Otro repositorio, o el mismo repositorio desde otra rama, presenta un subject distinto y no obtiene nada — aunque conozca todos los ids.

## 1. La identidad en Azure

Se usa una **managed identity de usuario**, no una app registration. Vive dentro de `rg-farmapato` como un recurso más: se administra con RBAC de suscripción sin tocar el directorio de Entra, desaparece con el resource group cuando el proyecto se apague, y es expresable en Bicep si algún día se añade `infra/`.

```bash
az identity create -n id-farmapato-gha -g rg-farmapato -l eastus2
```

De la salida se necesitan `clientId` (va a GitHub) y `principalId` (recibe el RBAC).

```bash
az identity federated-credential create --name gha-main \
  --identity-name id-farmapato-gha -g rg-farmapato \
  --issuer https://token.actions.githubusercontent.com \
  --subject "repo:<owner>@<ownerId>/<repo>@<repoId>:ref:refs/heads/main" \
  --audience api://AzureADTokenExchange
```

**El subject no es el que sale en la mayoría de los tutoriales.** Casi todos escriben `repo:owner/repo:ref:refs/heads/main`, y con ese valor la autenticación falla. GitHub emite hoy el **subject inmutable**, con el id numérico del owner y del repo incrustados, para que la credencial siga sirviendo si el repositorio o la cuenta cambian de nombre. La forma honesta de saber qué se va a presentar es preguntárselo a GitHub en vez de deducirlo:

```bash
gh api repos/<owner>/<repo>/actions/oidc/customization/sub --jq .sub_claim_prefix
```

Ese prefijo, más `:ref:refs/heads/main`, es el subject literal. Si no coincide, el fallo es `AADSTS700213` y el mensaje de error trae el subject presentado — comparar los dos es el diagnóstico completo.

El permiso va con **scope de contenedor, no de cuenta**. El comando es el mismo para cada contenedor que la identidad deba escribir, y hay que correrlo una vez por cada uno:

```bash
az role assignment create \
  --assignee-object-id <principalId> --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/<subscriptionId>/resourceGroups/rg-farmapato/providers/Microsoft.Storage/storageAccounts/stfarmapato/blobServices/default/containers/<contenedor>"
```

Repetirlo por contenedor parece burocracia hasta que se mira lo que compra. El lago tiene dos —`landing` con el dato crudo, `serving` con los marts— y el permiso de cada identidad se lee entero en una tabla:

| Identidad | `landing` | `serving` |
| --- | --- | --- |
| `id-farmapato-gha` (el pipeline) | Contributor | Contributor |
| El usuario que consume los marts | — | Reader |

**Quien lee los marts no puede leer el dato crudo, y eso no lo garantiza una convención sino la estructura.** Con un solo contenedor no habría forma de conceder lo uno sin lo otro: el contenedor es el scope más fino que admite un role assignment de datos, así que separar el acceso obliga a separar el contenedor. Es también la razón de que un contenedor nuevo no reparta permisos por accidente — nadie los tiene hasta que se otorgan.

**`--assignee-object-id` y no `--assignee`**: con el object id la CLI no consulta Graph, y así el comando no falla por la propagación de una identidad recién creada.

**En Git Bash sobre Windows**, cualquier `az` que reciba un `--scope` hay que lanzarlo con `MSYS_NO_PATHCONV=1` delante. Si no, el shell convierte `/subscriptions/...` en una ruta de Windows y Azure responde `MissingSubscription`, un error que no se parece en nada a la causa.

## 2. Las variables en GitHub

```bash
gh variable set AZURE_CLIENT_ID --body <clientId>
gh variable set AZURE_TENANT_ID --body <tenantId>
gh variable set AZURE_SUBSCRIPTION_ID --body <subscriptionId>
gh variable set AZURE_STORAGE_ACCOUNT --body stfarmapato
gh variable set AZURE_CONTAINER_LANDING --body landing
```

El contenedor va nombrado por su papel, no como «el contenedor», porque hay dos. `serving` no tiene variable todavía: la tendrá cuando exista `make export`, que es quien la lee.

Son `vars`, no `secrets`, **a propósito**: son GUIDs que sin la relación de confianza federada no otorgan absolutamente nada. Tratarlos como secretos daría a entender que ahí hay una credencial, y el punto entero de OIDC es que no la hay. (Los valores reales no se escriben en este documento por higiene, no por confidencialidad: están en la configuración del repo.)

## 3. Lo que hace el workflow

`.github/workflows/publish.yml` es `make publish` en un runner. Dos líneas cargan todo el peso:

- `permissions: id-token: write` — sin esto GitHub no emite el JWT y `azure/login` falla antes de hablar con Azure.
- `azure/login` — hace el intercambio y deja la CLI del runner autenticada.

El código Python **no cambia**: `DefaultAzureCredential` recorre su cadena y cae en `AzureCliCredential`, el mismo camino que en local tras `az login`. Por eso el generador es idéntico en las dos máquinas.

## 4. Comprobar

```bash
az identity federated-credential list --identity-name id-farmapato-gha -g rg-farmapato -o table
gh workflow run publish.yml && gh run watch
az storage fs file list -f landing --account-name stfarmapato --auth-mode login -o table
```

Prueba negativa, que es la que demuestra que el subject sirve para algo:

```bash
gh workflow run publish.yml --ref <otra-rama>
```

El job instala todo con normalidad y muere en `azure/login`:

```
AADSTS700213: No matching federated identity record found for presented
assertion subject 'repo:<owner>@<ownerId>/<repo>@<repoId>:ref:refs/heads/<otra-rama>'
```

Entra ID ni siquiera mira los permisos: el subject no coincide con ninguna federated credential y la conversación termina ahí.

## 5. Revocar

```bash
az identity federated-credential delete --name gha-main \
  --identity-name id-farmapato-gha -g rg-farmapato --yes
```

Corta el acceso en la siguiente corrida sin rotar nada ni tocar el repositorio. Los tokens ya emitidos caducan solos en una hora.

## 6. Idempotente no es atómico

`make publish` escribe **nueve blobs, uno por uno**. Si el job muere en el séptimo, la landing zone queda con siete tablas de la generación nueva y dos de la anterior. Eso es no ser atómico, y ninguna configuración del workflow lo arregla: la operación abarca nueve escrituras independientes y el almacenamiento de objetos no tiene transacciones.

Lo que sí es la publicación es **idempotente**: el generador es determinista por semilla, así que la misma configuración produce exactamente los mismos bytes. Reintentar no acumula ni duplica nada — converge al estado correcto. Son propiedades distintas y conviene no confundirlas: la idempotencia garantiza que el reintento arregla el problema, no que el problema no exista mientras tanto.

Se decidió **no** construir snapshots versionados (escribir a `raw/<timestamp>/` y mover un puntero al terminar, que es la forma estándar de volver atómica una escritura múltiple). El único escenario que muerde de verdad exige que alguien corra `load-cloud` justo entre el fallo y el reintento, y hoy la publicación es un `workflow_dispatch` manual con un solo operador. Construir el versionado ahora sería resolver un problema que el proceso ya evita.

El disparador para construirlo sería que algo automático leyera de la landing zone sin humano en medio — un job programado de carga, u otro consumidor del lago. Ahí el estado intermedio deja de ser improbable y pasa a ser cuestión de tiempo.
