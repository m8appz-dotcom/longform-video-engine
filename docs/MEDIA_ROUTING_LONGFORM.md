# Routing de medios longform

El motor decide medios por factibilidad del beat, no por una escalera fija de
proveedores. El guion y la narracion aprobada permanecen bloqueados.

## Contrato por escena

Cada shot declara:

```json
{
  "proofKind": "human_action | real_event | third_party_commentary | cultural_reference | product_inspection | physiological_mechanism | comparison | exact_ui_state | presenter | abstract_concept",
  "beatRole": "proof | explanation | action | pattern_interrupt",
  "requiredEvidence": "lo que debe verse para sostener la narracion",
  "preferredMedium": "pexels",
  "forbiddenSubstitutions": ["clip_extractor", "motion-card-as-evidence"],
  "evidenceMode": "illustrative | demonstrative | documentary | data_exact",
  "requiresReadableData": false,
  "requiresContinuity": false,
  "temporalAction": "single | multi_step",
  "temporalEvidenceMode": "implied | initial_final | continuous",
  "requiresObservedTransition": false,
  "stateCount": 1,
  "detailSalience": "focal | required | incidental",
  "continuityGroup": "grupo-estable",
  "peoplePolicy": "forbidden | contextual | required",
  "presenterAllowed": false,
  "maxFaceAreaRatio": 0.2,
  "evidenceMustRemainDominant": true,
  "noveltyKey": "accion-producto-encuadre",
  "evidenceBeatId": "EB001",
  "routePlan": ["pexels", "image", "omni"]
}
```

Cada shot tambien lleva `MotionSpec` (`purpose`, `visualPrimitive`, `timeline`,
`camera`, `transitions`, `sfxCues`, `mustNotCover`, `fallback`) y, solo cuando
corresponde, `stopMotionIntent` y `whyStopMotion`.

El router aplica estas reglas antes de cualquier llamada pagada:

- `human_action`: clip del usuario, Pexels, imagen y Omni. Nunca Clip Extractor.
- `real_event`, `third_party_commentary` y `cultural_reference`: Clip Extractor con fuente identificable. Si falla, se reescribe el beat o se pide fuente; nunca se fabrica un sustituto.
- `exact_ui_state` o datos legibles: UI determinista.
- `comparison`: par de imagenes, Omni y ComparisonProof de Remotion. Cutout solo entra con una intencion narrativa explicita.
- `physiological_mechanism`: imagen/ilustracion, Remotion y Omni. Cutout solo puede apoyar como tratamiento ilustrativo intencional.
- `abstract_concept`: imagen, UI, Omni o motion graphics; Cutout no es un fallback automatico.
- `presenter`: Kreado; si no entrega, se usa un reemplazo visual compatible y el run continua con trazabilidad.
- `multi_step` describe la narracion, no obliga a video. Una imagen puede implicar accion; dos imagenes muestran estado inicial/final. Video solo es obligatorio cuando la trayectoria debe observarse.

El modo temporal manda sobre el formato: `implied` admite una imagen;
`initial_final` materializa dos estados controlados; `continuous` exige que el
espectador vea trayectoria, tecnica, velocidad, orden o continuidad. El QA no
rechaza una imagen solo porque no se mueve.

Stop motion no ocupa un escalon fijo. Es un tratamiento opt-in para comprimir
una transformacion, introducir surrealismo ludico, coreografiar objetos o crear
un ancla visual breve. Se excluye de evidencia documental seria, movimiento
humano fluido, UI exacta y relleno por falta de metraje. Requiere una razon y
una coreografia concretas; dos secuencias adyacentes o el mismo intento repetido
en menos de 35 segundos se rechazan antes de llamar al proveedor.

Las combinaciones contradictorias bloquean la etapa de plan. El texto visible
de cards se limita a cuatro palabras y 32 caracteres.

## Consultas y presupuesto

Cada proveedor recibe una consulta propia:

- Clip Extractor: titulo, fuente, canal o evento real identificable. No acepta conceptos de B-roll.
- Pexels: sujeto, accion fisica y entorno; maximo tres variantes.
- Imagen: composicion 16:9, camara, identidad, continuidad y restricciones.
- Cutout Motion: un background, 1-3 props concretos, relacion visual y la narracion aprobada sin cambios.
- Omni: estado inicial, progresion de accion y estado final.
- UI: template y datos estructurados extraidos de la narracion bloqueada.

Por defecto cada escena dispone de `180` segundos, configurable con
`LONGFORM_SCENE_ASSET_BUDGET_SECONDS`. Se inspeccionan como maximo tres
variantes y se descargan como maximo dos candidatos. El ranker compara ajuste
a evidencia, calidad tecnica, credibilidad, movimiento util, continuidad,
novedad, sincronizacion TTS, costo y tiempo. Solo existe un reintento dirigido
por `evidenceBeatId`; el rechazo modifica la consulta siguiente.

## Gestor de proveedores

El preflight prueba salud real y clasifica cada servicio como `healthy`,
`recovering`, `unavailable` o `blocked_external`. Cutout y Kreado son servicios
administrados: usan lock de arranque, PID, logs, un solo reinicio y readiness.
Al recuperarse se limpia el circuit breaker. Clip Extractor tambien puede
administrarse cuando el proyecto declara comando y directorio de arranque; si
es un servicio externo sin control local queda `blocked_external`, no se finge
que fue iniciado.

## Sistema visual agnostico

`DesignProfile` se resuelve por proyecto desde una URL, instrucciones directas
o tokens explicitamente provistos. El extractor registra hashes de HTML, CSS y
bundles del mismo origen; deriva colores, tipografias, composicion, duraciones,
keyframes y presencia verificable de Three.js/WebGL/canvas/shaders/particulas.
La referencia nunca se convierte en una marca hardcoded del motor.

El renderer consume `tokens.colors`, `tokens.semanticColors`, `composition`,
`motion` y `rendering`. El fallback `frontier-dark-v1` es el sistema oscuro,
tipografico y de hairlines del motor; no contiene la paleta de Adrian Yepez. Las
capacidades avanzadas funcionan como permisos, no como una cuota:
solo se activan en conceptos abstractos con representacion compatible. Una
capacidad de estilo nunca puede cambiar el tipo de evidencia exigido por el beat.

`MotionSpec` separa el significado del componente. Remotion usa primitivas
genericas (`comparison`, `timeline`, `process`, `chart`, `diagram`, `anatomy`,
`magnifier`, `particles`, `three_scene`, `editorial`) cuyos datos vienen del
plan. Las animaciones usan `useCurrentFrame` e `interpolate`; no dependen de CSS
en tiempo real. Los SFX se disparan por eventos semanticos y se limitan a dos
cues por shot con separacion minima.

## Cutout Motion REST

Cutout es opt-in y solo puede entrar en conceptos ilustrativos, mecanismos,
comparaciones y progresiones. No sustituye accion humana real, eventos,
interfaces, etiquetas legibles, inspeccion de producto ni presentador.

```env
CUTOUT_PROVIDER_ENABLED=1
CUTOUT_BASE_URL=http://127.0.0.1:8000
CUTOUT_ASSET_PROVIDER=codex-oauth
CUTOUT_STYLE_SCOPE=project design profile
CUTOUT_MOTION_PLANNER=rules
CUTOUT_PROMPT_REFINER=none
```

El adaptador llama `/health` y `/analyze` antes de crear un job. Rechaza escenas
sin 1-3 props, sin movimiento, demasiado cortas o incompatibles con el modo de
evidencia. Crea el job con `script_writer=none` y `dry_run_audio=true`, elimina
todo audio recibido, normaliza a la resolucion/FPS longform y nunca hace loop.
La duracion se ajusta con retiming proporcional (`setpts`) dentro de limites
0.85-1.50, conservando la posicion relativa de las entradas visuales.
Si falla, el router continua con los providers existentes.

Como los endpoints GET de jobs y artefactos no tienen autenticacion propia, el
servicio debe permanecer en loopback. Un host remoto exige
`CUTOUT_ALLOW_REMOTE=1` y un proxy autenticado.

## QA y procedencia

Antes del juez visual se aplican filtros multiframe de orientacion, resolucion,
bitrate relativo al movimiento, nitidez, bloqueos de compresion, reescalado,
FPS, watermarks, OCR, texto denso, software equivocado y politica contextual de
personas. Un rostro es valido cuando participa en la accion y la evidencia
domina; se rechaza cuando funciona como presentador accidental. Luego se valida
el encaje semantico.

Los detalles se juzgan a 1080p y velocidad normal. Un elemento `focal` debe ser
claro; uno `required` debe sostener la afirmacion; un detalle `incidental` que
un humano no percibiria no bloquea. Un envase blanco en primer plano sigue
siendo fallo, pero no se hace pixel-peeping de etiquetas diminutas de fondo.

Antes de finalize se crea un contact sheet global y se comprueban continuidad,
repeticion, evidencia por capitulo, novedad y no mas de dos usos consecutivos
del mismo medio o template. `ComparisonProof`, `AnatomyExplainer`,
`ProcessSteps`, `ProductInspection`, `Timeline`, `EditorialCard` y
`VerifiedEndScreen` viven como templates de Remotion: el sistema visual es
estable, pero los datos son dinamicos. Una card explicativa nunca sustituye la
prueba visual.

El CTA se resuelve contra el catalogo autenticado del canal antes de producir y
se revalida antes de QA/publicacion. Debe conservar ID, titulo, canal, URL,
visibilidad y fecha de verificacion; un video inexistente o privado bloquea.

El watchthrough audiovisual sube un proxy completo con video y audio a Gemini
Files API y revisa el montaje una vez, con toda la promesa, audiencia, timeline,
contratos de evidencia y politica perceptual. No usa votos repetidos para borrar
un rechazo. Escucha narracion, musica y SFX, identifica drop-offs por timestamp
y distingue blockers de preferencias editoriales.

El aprendizaje registra escena, provider, causa y feedback humano ligado al
hash del master. La QA automatica sola no promociona sesgos. Una preferencia
positiva exige evidencia tecnica repetida y aprobacion humana en dos runs; una
penalizacion de provider exige dos rechazos que nombren explicitamente ese
provider o proof kind. Las restricciones duras nunca se relajan por aprendizaje.

Artefactos principales:

```text
provider_events.jsonl
04_provider_summary.json
04_evidence_set_qa.json
reviews/evidence_set_contact_sheet.jpg
04_assets_manifest.json
04_scene_decisions.json
provider_manager.json
08_master_qa.json
```

`04_provider_summary.json` distingue outputs producidos de assets finalmente
seleccionados y lista la fuente sobreviviente por escena. Los assets manuales
deben entrar con procedencia:

```powershell
python tools\import_asset.py D:\assets\clip.mp4 --run-id video-001 `
  --shot-id S0004 --kind video --description "aplicacion real de crema" `
  --license "clip suministrado por el usuario"
```
