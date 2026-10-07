# Longform Engine

Motor post-guion para videos horizontales de YouTube. Es un fork del motor de
Reels, pero no reemplaza el laboratorio creativo: recibe un guion ya elegido y
bloqueado, y se encarga de TTS, alineacion, direccion visual, assets, Remotion,
render y QA.

## Limite de responsabilidad

```text
Laboratorio YouTube: datos -> empaque -> angulo -> guiones -> avatar elige
                                      |
                                      v
Longform Engine: ApprovedScript -> voz -> plan -> assets -> Remotion -> QA
```

El texto narrado no se reescribe dentro de este repositorio. El hash SHA-256 del
guion se valida al comienzo de cada etapa.

Importa directamente el ganador del laboratorio:

```powershell
python tools\build_approved_script.py 24_guion_duelo_ganador.md contracts\video.json `
  --run-id video-001 --title "Titulo cerrado" --thumbnail-promise "TEXTO" `
  --target-minutes 3 --audience-profile "Perfil observado de al menos 40 caracteres"
```

## Produccion longform

```powershell
Copy-Item .env.example .env # completar credenciales una vez
npm install --prefix remotion
python -m engine.longform_pipeline validate contracts\mi_guion_aprobado.json
python -m engine.longform_pipeline full contracts\mi_guion_aprobado.json
```

La corrida completa ejecuta un preflight persistente antes de gastar llamadas,
genera primero un borrador 960x540 con todo el audio y solo habilita el master
si ese borrador pasa QA visual. Los caches mock y real tienen firmas distintas:
un asset de prueba nunca puede colarse en una produccion.

Para probar sin APIs, las variables exportadas en la sesion tienen precedencia:

```powershell
$env:PROVIDER_MODE = 'mock'
python -m engine.longform_pipeline props contracts\mi_guion_aprobado.json
```

Artifacts por corrida:

```text
work/longform_runs/<run_id>/       contratos, planes, manifest y QA
remotion/public/runs/<run_id>/     audio y assets consumidos por Remotion
out/longform/<run_id>/master.mp4   master final
```

La prioridad de reutilizacion sigue siendo clip suministrado por el usuario y
biblioteca local. Despues, un router de factibilidad elige proveedor segun la
evidencia que exige cada beat: accion humana, evento real, comentario ajeno,
referencia cultural, estado UI exacto, concepto abstracto, proceso temporal o
presentador. Clip Extractor no es stock: solo recupera una fuente real e
identificable, como un suceso, declaracion, video ajeno, pelicula, serie o video
musical. Pexels resuelve acciones humanas genericas. No se consulta Pexels para
una interfaz exacta ni se pide a una imagen fija demostrar varios pasos. Cada
video debe cubrir su shot sin loop; cada archivo se usa una sola vez por
SHA-256 y queda indexado con procedencia, etiquetas y uso historico. El avatar aparece
exactamente dos veces, a pantalla completa, siempre 16:9, centrado, sin recorte
y dentro de un frame coherente con la estetica.

El contrato, routing, presupuestos, compiladores y artefactos de auditoria se
documentan en [docs/MEDIA_ROUTING_LONGFORM.md](docs/MEDIA_ROUTING_LONGFORM.md).

Las motion cards no tienen una cuota artificial: se admiten cuando explican,
comparan o dinamizan, pero nunca reemplazan la evidencia y no se repite el
mismo medio o template mas de dos veces. El director evalua movimiento util,
sincronizacion con TTS, evidencia por capitulo y variedad controlada; no fuerza
porcentajes de stock, video o cards. Los envases generados deben llevar una
etiqueta ficticia legible; se bloquean empaques blancos, texto absurdo y marcas
reales.

El estilo tampoco esta codificado al canal. Cada contrato puede declarar
`design_source` (URL o instrucciones) y `design_profile`. El preflight extrae
paleta, tipografia, composicion, tiempos de animacion y recursos avanzados
observables (Three.js, WebGL, canvas, shaders o particulas), conserva evidencia
y genera un `DesignProfile` versionado. Remotion recibe ademas un `MotionSpec`
por shot: proposito, primitiva, timeline, camara, transiciones, zonas que no se
pueden tapar y cues semanticos de SFX. Las animaciones son deterministas por
frame; el contenido nunca queda hardcoded dentro de un componente.

El perfil builtin `frontier-dark-v1` usa canvas `#0A0A0A`, blanco como color
primario, Inter 400, Geist Mono, hairlines, tarjetas de 8 px y ninguna sombra.
Color de marca, colores semanticos, densidad, padding, radios, proporcion de
split, entrada e intensidad pueden reemplazarse desde el perfil del proyecto. El
HTML/CSS/JS de una URL solo se inspecciona como evidencia: nunca se ejecuta ni se
copia al render. Three.js, WebGL o particulas quedan autorizados unicamente para
shots abstractos que los pidan semanticamente; no sustituyen evidencia literal,
anatomia, producto ni accion humana.

La musica de produccion proviene de Suno mediante navegador autenticado, porque
no se simula una API inexistente. Despues de descargar un tema con derechos de
la cuenta Pro, se ingresa con procedencia verificable:

```powershell
python tools\ingest_suno_music.py D:\descargas\tema.mp3 `
  --run-dir work\longform_runs\video-001 `
  --source-url "https://suno.com/song/..." `
  --prompt "instrumental calido y creible, sin voz" `
  --mood "calido, explicativo"
```

Sin ese manifiesto Suno, una corrida real no produce master. El compositor
mezcla musica baja bajo la narracion, SFX discretos y un CTA hablado que nombra
el video siguiente; la pantalla final se sostiene entre 8 y 10 segundos.

Para el procedimiento operativo completo, incluyendo la ventana nativa `Save As`
de Windows, archivos `.tmp`, validacion con `ffprobe`, preflight y reanudacion,
leer [docs/PRODUCCION_SUNO_Y_PREFLIGHT.md](docs/PRODUCCION_SUNO_Y_PREFLIGHT.md).
El helper materializa una descarga temporal estable antes de ingerirla:

```powershell
python tools\finalize_suno_download.py `
  --downloads-dir "$env:USERPROFILE\Downloads" `
  --output "$env:USERPROFILE\Downloads\video_suno.mp3"
```

## Contrato de entrada

Usa `contracts/approved_script.schema.json`. Los clips del usuario pueden llevar
`shot_ids` para asignacion exacta o una descripcion para matching semantico:

```json
{"path":"D:/clips/aplicacion.mp4","description":"aplicar crema en abdomen","shot_ids":["S0004"],"start_ms":1200}
```

## Verificacion

```powershell
python -m unittest discover -s tests -v
npm run typecheck --prefix remotion
Push-Location remotion; npx remotion versions --log=verbose; Pop-Location
```

---

## Motor vertical heredado

Motor de reels verticales (1080x1920) 100% agnostico de dominio. Reescritura limpia de reel-engine con las mismas ideas y proveedores, y una arquitectura de UNA fuente de verdad.

## Principios
- **Una fuente de verdad.** Prompts en `prompts/`. Geometria y registro de componentes en `shared/core.json` (correr `python scripts/codegen.py` tras editarlo: genera `engine/_generated.py` y `remotion/src/generated.ts`). Umbrales en los validadores. El skill (`skill/reel-director.md`) orquesta sin duplicar reglas.
- **Etapas puras + circuit breaker.** `python -m engine.pipeline {audition|plan|props|render}`. Cada etapa corre una vez; los fallos se registran en `work/pipeline_state.json`; al tope de reintentos (`MAX_STAGE_RETRIES=2`) el pipeline para y reporta. Nada de bucles silenciosos.
- **declared_only.** Remotion decide geometria/animacion; el contenido (texto, valores, items) viene SIEMPRE declarado en el plan. Anchors por frase literal del guion.
- **Core agnostico.** Nada de dominio en motor/skill/prompts; los dominios viven en `plugins/`.

## Layout
```
contracts/   reel_plan.schema.json (+ planes)
shared/      core.json (fuente unica de geometria/registro)
prompts/     script.md + structure_{arc,case,countdown}.md
engine/      pipeline, voice (TTS+align), props_build, validate_plan/props, qa (juez LLM), preview (contact sheet), audition, resolve, aligner
providers/   core (ElevenLabs/Pexels/ClipExtractor/Cutout/Google/imagen), kreado, codex_oauth
remotion/    renderer modular (src/components, src/layers, generated.ts)
skill/       reel-director.md (el DIRECTOR)
plugins/     dominios (SFX/contratos especificos)
references/  reels de referencia del nicho (formato, nunca contenido)
```

## Quickstart
```powershell
cp .env.example .env   # rellenar llaves
cd remotion && npm install && cd ..
python scripts/codegen.py
python -m engine.pipeline plan contracts/ejemplo_fondo_emergencia.json
python -m engine.pipeline props contracts/ejemplo_fondo_emergencia.json
python -m engine.pipeline render
```
