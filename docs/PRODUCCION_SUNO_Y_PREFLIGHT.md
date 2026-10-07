# Produccion: Suno y preflight

Esta guia evita los dos errores que mas facilmente contaminan una corrida:

1. confundir una descarga iniciada con un MP3 ya materializado;
2. reanudar un run con artefactos `mock` cuando la corrida actual es `real`.

## Regla de oro

Una produccion no avanza por tener un track visible en Suno. Avanza solo cuando
existen estas tres pruebas locales:

- el MP3 pasa `ffprobe` y tiene duracion mayor que cero;
- `music_manifest.json` declara `provider: suno`, URL, prompt, licencia y un
  track existente;
- `00_provider_preflight.json` y los gates posteriores estan en `PASS`.

No se debe pegar una URL de audio inventada ni usar un archivo `mock_music.wav`
en una corrida real.

## Preparar la sesion

Ejecutar desde `D:\longform-engine` en una PowerShell limpia:

```powershell
$env:PROVIDER_MODE = "real"
$env:NO_PROVIDER_CALLS = "0"
$env:ALLOW_ASSET_FALLBACKS = "0"
$env:AI_QA_ENABLED = "1"
$env:AI_QA_REQUIRED = "1"
$env:AI_QA_PROVIDER = "codex"

python -m engine.longform_pipeline validate contracts\video.json
```

Antes de `full`, comprobar las credenciales y servicios que el preflight exige:

```powershell
Get-ChildItem Env:PROVIDER_MODE,Env:ELEVENLABS_API_KEY,Env:ELEVENLABS_VOICE_ID
Test-Path "$env:CODEX_HOME\auth.json"
Test-Path remotion\node_modules\@remotion
ffmpeg -version
ffprobe -version
node --version
```

No continuar si una variable sale vacia, si `CODEX_HOME\auth.json` no existe,
si falta `ffprobe` o si Remotion no tiene dependencias.

## Flujo correcto de Suno

Suno se usa mediante Chrome autenticado. No existe una API de Suno en este
motor y no se debe simular.

1. Abrir Suno con la cuenta Pro correcta.
2. Generar el track usando `description` solo para genero, instrumentos,
   tempo, estructura y mezcla.
3. Poner restricciones como voces, letras o drops en `Exclude`.
4. En la pagina del track abrir `...` -> `Download` -> `MP3 Audio`.
5. Completar la ventana nativa `Save As` de Windows.
6. Esperar a que termine la escritura. Chrome puede dejar el archivo como
   `.tmp`; eso no significa que el contenido sea invalido.
7. Materializarlo con el helper:

```powershell
python tools\finalize_suno_download.py `
  --downloads-dir "$env:USERPROFILE\Downloads" `
  --output "$env:USERPROFILE\Downloads\video_suno.mp3"
```

El helper solo acepta un archivo local estable que `ffprobe` identifica como
audio con duracion. Si no encuentra uno, detenerse: no renombrar a ciegas un
archivo parcial y no continuar con musica mock.

## Ingestar la musica

Usar el prompt exacto guardado en `suno_request.json`. No copiar al prompt de
Suno el titulo del video, la audiencia, la edad, el idioma editorial o notas de
produccion.

```powershell
python tools\ingest_suno_music.py "$env:USERPROFILE\Downloads\video_suno.mp3" `
  --run-dir "work\longform_runs\video-001" `
  --source-url "https://suno.com/song/ID_REAL" `
  --prompt "PROMPT_EXACTO_DE_suno_request.json" `
  --mood "warm, credible, modern organic electronic" `
  --license "Suno Pro account; manually downloaded MP3"
```

Comprobar el manifiesto antes de producir:

```powershell
$m = Get-Content -Raw work\longform_runs\video-001\music_manifest.json | ConvertFrom-Json
$m.provider
$m.source_url
$m.license
Test-Path $m.tracks[0].path
ffprobe -v error -show_entries format=duration,format_name `
  -of default=noprint_wrappers=1 $m.tracks[0].path
```

El valor de `provider` debe ser `suno`. La URL debe ser la del track observado,
no una URL de ejemplo. La licencia debe reflejar la cuenta y el modo real de
obtencion.

## Run limpio y reanudacion

No se debe cambiar `PROVIDER_MODE` a mitad de un run. El motor bloquea esa
mezcla en `props`, `render` y `qa`, pero el operador debe prevenirla:

```powershell
python -m engine.longform_pipeline full contracts\video.json
python -m engine.longform_pipeline status contracts\video.json
```

Si el run ya produjo un plan `mock` y ahora se quiere produccion real, crear un
`run_id` nuevo o limpiar el run de forma controlada. No reutilizar silenciosamente
el plan, la voz, los assets ni el manifest mock.

La reanudacion es valida solo si se mantienen:

- el mismo `script_hash`;
- el mismo `providerMode`;
- el mismo contrato bloqueado;
- los manifests y assets con paths existentes;
- los gates anteriores en `PASS`.

## Detenciones obligatorias

Detener la corrida y corregir antes de renderizar si ocurre cualquiera de estos
casos:

- aparece `mock_music.wav` en un run real;
- el MP3 no tiene duracion o `ffprobe` falla;
- falta `music_manifest.json` o no declara `provider: suno`;
- el preflight marca `FAIL`;
- el plan reanudado tiene otro `providerMode`;
- el audio TTS queda fuera de `LONGFORM_DURATION_TOLERANCE`;
- el avatar no es 16:9, esta recortado o no aparece exactamente dos veces;
- un clip se repite por SHA-256, se hace loop o contradice el audio;
- un envase generado aparece sin etiqueta ficticia legible;
- el QA final no tiene evidencia del master y de la transcripcion.

## Evidencia que se conserva

Cada run debe conservar, como minimo:

```text
work/longform_runs/<run_id>/00_provider_preflight.json
work/longform_runs/<run_id>/01_contract_validation.json
work/longform_runs/<run_id>/02_voice_alignment.json
work/longform_runs/<run_id>/04_assets_manifest.json
work/longform_runs/<run_id>/05_resolved_plan.json
work/longform_runs/<run_id>/music_manifest.json
work/longform_runs/<run_id>/08_master_qa.json
out/longform/<run_id>/master.mp4
```

El archivo de Suno debe conservar URL, prompt, licencia, hash local y duracion.
Eso permite auditar el origen y volver a usar el asset sin regenerarlo.
