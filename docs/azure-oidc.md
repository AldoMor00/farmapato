# OIDC: cómo se autentica GitHub Actions contra Azure

La landing zone en ADLS Gen2 no tiene llave: el storage account se creó con `--allow-shared-key-access false`, así que el acceso sólo se otorga por RBAC a una identidad. En local esa identidad es la del `az login`. En CI no hay usuario, y la respuesta **no** es un client secret guardado en GitHub: es una credencial federada.

## Qué gana el proyecto con esto

Un client secret es una credencial de larga vida que hay que rotar a mano y que, filtrada, sirve hasta que alguien la revoque. Con OIDC no existe ese dato. La confianza es una **relación declarada** entre GitHub y Entra ID, y lo que viaja es un token que caduca en una hora.

```
1. El runner le pide a GitHub un JWT.
   GitHub lo firma y le mete quién corre qué:
   subject = repo:AldoMor00/farmapato:ref:refs/heads/main

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
  --subject repo:AldoMor00/farmapato:ref:refs/heads/main \
  --audience api://AzureADTokenExchange
```

El permiso va con **scope de contenedor, no de cuenta**: la identidad puede escribir en `landing` y en nada más, incluidos los contenedores que se creen después.

```bash
az role assignment create \
  --assignee-object-id <principalId> --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/<subscriptionId>/resourceGroups/rg-farmapato/providers/Microsoft.Storage/storageAccounts/stfarmapato/blobServices/default/containers/landing"
```

**`--assignee-object-id` y no `--assignee`**: con el object id la CLI no consulta Graph, y así el comando no falla por la propagación de una identidad recién creada.

**En Git Bash sobre Windows**, cualquier `az` que reciba un `--scope` hay que lanzarlo con `MSYS_NO_PATHCONV=1` delante. Si no, el shell convierte `/subscriptions/...` en una ruta de Windows y Azure responde `MissingSubscription`, un error que no se parece en nada a la causa.

## 2. Las variables en GitHub

```bash
gh variable set AZURE_CLIENT_ID --body <clientId>
gh variable set AZURE_TENANT_ID --body <tenantId>
gh variable set AZURE_SUBSCRIPTION_ID --body <subscriptionId>
gh variable set AZURE_STORAGE_ACCOUNT --body stfarmapato
gh variable set AZURE_STORAGE_CONTAINER --body landing
```

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
az storage fs file list -f landing --path raw --account-name stfarmapato --auth-mode login -o table
```

Prueba negativa, que es la que demuestra que el subject sirve para algo:

```bash
gh workflow run publish.yml --ref <otra-rama>
```

El job instala todo con normalidad y muere en `azure/login`:

```
AADSTS700213: No matching federated identity record found for presented
assertion subject 'repo:AldoMor00/farmapato:ref:refs/heads/<otra-rama>'
```

Entra ID ni siquiera mira los permisos: el subject no coincide con ninguna federated credential y la conversación termina ahí.

## 5. Revocar

```bash
az identity federated-credential delete --name gha-main \
  --identity-name id-farmapato-gha -g rg-farmapato --yes
```

Corta el acceso en la siguiente corrida sin rotar nada ni tocar el repositorio. Los tokens ya emitidos caducan solos en una hora.
