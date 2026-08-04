# El gasto en Azure y su guardarraíl

Todo lo que este proyecto tiene en Azure vive dentro de un solo resource group, `rg-farmapato` en `eastus2`:

| Recurso | Qué es | Qué cuesta |
| --- | --- | --- |
| `stfarmapato` | Storage account con el contenedor `landing` (ADLS Gen2) | Almacenamiento por GB-mes + operaciones por cada 10,000 |
| `id-farmapato-gha` | Managed identity de usuario para el OIDC de Actions | Nada |
| `budget-farmapato` | El presupuesto que vigila lo anterior | Nada |

No hay cómputo. Ninguna VM, ningún Synapse, ninguna Data Factory — la única forma de que este proyecto genere un recibo es el almacenamiento, y el dato crudo completo pesa unos **28 MB**. Una publicación son **nueve operaciones de escritura**, una por tabla. El orden de magnitud del gasto mensual es de centavos, y la línea del recibo redondea a cero.

Eso no hace innecesario el presupuesto. Lo hace barato de tener y valioso el día que se pruebe un servicio caro por curiosidad, que es exactamente cuando nadie está mirando el portal.

## El presupuesto

```bash
az consumption budget list -o json
```

- **Scope**: el resource group `rg-farmapato`, no la suscripción.
- **Monto**: 2 USD al mes, grano mensual.
- **Dos avisos por correo**, y son de tipos distintos a propósito:
  - **gasto real > 80%** — llega cuando ya pasó. Sirve de bitácora: algo consumió de verdad.
  - **gasto pronosticado > 100%** — llega *antes*, cuando Azure extrapola el ritmo del mes y ve que va a rebasar. Es el que da tiempo de reaccionar.

Un presupuesto con un solo umbral obliga a elegir entre enterarse tarde y enterarse de falsos positivos. Con los dos, el pronóstico avisa y el real confirma.

Los 2 USD no son una estimación del gasto esperado: son un umbral deliberadamente pegado al suelo. Como el gasto normal es de centavos, cualquier cosa que se acerque a 2 dólares es, por definición, algo que no debería estar corriendo.

## El límite que hay que conocer

**Un presupuesto con scope de resource group sólo ve lo que se gasta dentro de ese resource group.** Si algún día se crea un recurso fuera de `rg-farmapato` —otro RG, o suelto en la suscripción— este presupuesto no lo mira y no avisa de nada.

Es la contrapartida de la misma decisión que se tomó para la identidad: mantener todo el proyecto dentro de un RG que se apaga con un `az group delete`. La consecuencia es que el guardarraíl es del proyecto, no de la cuenta. Si la suscripción llega a alojar algo más, el presupuesto que falta es uno a nivel suscripción, y son dos presupuestos distintos, no uno movido.

## La suscripción es un trial, y eso caduca

```
quotaId:       FreeTrial_2014-09-01
spendingLimit: On
```

Con el límite de gasto en `On` no hay riesgo de recibo sorpresa: agotado el crédito, Azure **deshabilita los recursos** en vez de cobrar. Es un freno duro, más fuerte que cualquier presupuesto — pero frena apagando, y lo que se apaga incluye la landing zone.

Conviene decirlo sin adornos: **"la fuente de verdad es el lago" es cierto mientras la suscripción esté viva**, y su vida útil hoy depende de un trial. El plan al terminar el mes gratis es migrar a otra suscripción.

Esa migración no es gratis en trabajo, pero sí es corta, y el runbook de [`azure-oidc.md`](azure-oidc.md) *es* el plan: crear el storage account y la managed identity en la suscripción nueva, rehacer la federated credential y el role assignment, actualizar `AZURE_CLIENT_ID` y `AZURE_SUBSCRIPTION_ID` en las variables del repo, y recrear el presupuesto.

Lo que **no** hay que migrar son los datos. Un `make publish` contra el contenedor nuevo los deja byte por byte idénticos, porque el generador es determinista. Mover 28 MB entre suscripciones sería más trabajo que recalcularlos.

## Comprobar

```bash
az consumption budget list --query "[].{nombre:name, monto:amount, gastado:currentSpend.amount, scope:resourceGroup}" -o table
az consumption usage list --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD> -o table
```

El destinatario de los avisos está en la configuración del presupuesto, no en este documento — por higiene, igual que los ids de `azure-oidc.md`.
