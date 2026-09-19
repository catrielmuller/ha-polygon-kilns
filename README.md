# Polygon Kilns para Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/catrielmuller/ha-polygon-kilns/actions/workflows/validate.yml/badge.svg)](https://github.com/catrielmuller/ha-polygon-kilns/actions/workflows/validate.yml)

**[English](README.en.md) | [Français](README.fr.md)**

Integración custom de Home Assistant para los hornos de cerámica **Polygon**. Habla directamente con el backend de Firebase de Polygon: no hace falta ningún hardware ni servidor adicional.

## Funcionalidades

- **Monitoreo** por horno: temperatura, setpoint, estado, etapa, progreso, ETA, tiempo transcurrido, energía, costo, señal WiFi, última horneada (con detalle del histórico) y fallas (termocupla, sensor, sobrecalentamiento, conectividad).
- **Control**: botones y servicios para iniciar un programa y detener el horno.
- **Inicio programado** (lo que la app oficial no tiene): elegí programa + fecha/hora, armá el switch, y la integración dispara el inicio a esa hora. Tanto el inicio programado como el programa seleccionado sobreviven reinicios de Home Assistant.
- **CRUD de programas**: servicios para crear, actualizar y borrar programas de cocción (etapas con rampa/temperatura/meseta).
- Soporta hornos **propios y compartidos**.

## Instalación

### HACS (repo custom)

1. HACS → Integraciones → menú ⋮ → *Custom repositories* → agregá este repo como *Integration*.
2. Instalá **Polygon Kilns** y reiniciá Home Assistant.

### Manual

Copiá `custom_components/polygon_kilns` al directorio `custom_components` de tu configuración y reiniciá.

## Configuración

Ajustes → Dispositivos y servicios → *Agregar integración* → **Polygon Kilns**. Usá el email y la contraseña de tu cuenta de la app Polygon.

> Si tu cuenta solo usa Google/Apple Sign-In, primero establecé una contraseña para la cuenta (la integración usa el proveedor email/password de Firebase).

El intervalo de actualización se ajusta en las opciones de la integración (15–120 s, default 30 s).

## Inicio programado

Cada horno expone tres entidades de control:

1. `select.<horno>_programa_a_iniciar` — elegí el programa.
2. `datetime.<horno>_inicio_programado` — elegí fecha y hora.
3. `switch.<horno>_inicio_programado_activo` — armá el inicio.

Cuando llega la hora, la integración llama al backend de Polygon (`requestStart`) y desarma el switch. Si el horno no está disponible o está horneando, se crea una notificación persistente y el inicio no se ejecuta.

También se puede hacer por servicio:

```yaml
action: polygon_kilns.start_schedule
data:
  kiln_id: K1117
  schedule_name: GRES CONO 6
  start_time: "2026-09-20T07:30:00"  # opcional; sin esto inicia ahora
```

## Servicios

| Servicio | Descripción |
| --- | --- |
| `polygon_kilns.start_schedule` | Inicia un programa (ahora o con `start_time`). |
| `polygon_kilns.stop_schedule` | Detiene la horneada en curso. |
| `polygon_kilns.create_schedule` | Crea un programa con etapas `{ramp, temp, hold}`. |
| `polygon_kilns.update_schedule` | Modifica nombre y/o etapas de un programa. |
| `polygon_kilns.delete_schedule` | Borra un programa. |

Ejemplo de creación de programa:

```yaml
action: polygon_kilns.create_schedule
data:
  kiln_id: K1117
  schedule_name: BIZCOCHO LENTO
  sched_num: 11
  stages:
    - { ramp: 100, temp: 500, hold: 0 }
    - { ramp: 150, temp: 980, hold: 15 }
```

## Limitaciones conocidas

- Si tu acceso al horno es **compartido** (no sos el dueño), las reglas de Firestore pueden impedir detener el horno o editar programas; la integración lo informa con un error claro. La lectura siempre funciona.
- El backend no expone API local: todo pasa por la nube de Polygon.

## Desarrollo

### Devcontainer

El repo incluye un devcontainer listo para probar en un Home Assistant real:

1. Abrí el repo en VS Code → *Reopen in Container*.
2. Al construirse, `scripts/setup` instala las dependencias en `.venv`.
3. Ejecutá `bash scripts/develop` → Home Assistant queda en `http://localhost:8123` con la integración cargada.
4. Agregá la integración desde la UI con tu cuenta real.

### Tests

```sh
bash scripts/setup
.venv/bin/pytest
```

Los tests usan fixtures con documentos reales (saneados) del horno `K1117`.
