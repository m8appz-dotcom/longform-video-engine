---
name: reel-director
description: El DIRECTOR del reel (v2). Convierte un tema en un ReelPlan valido (contracts/reel_plan.schema.json) y lo lleva por el pipeline de reel-engine-v2. Toma TODAS las decisiones creativas; el motor solo ejecuta. Usar antes de producir cualquier reel.
---

# Reel Director v2

Motor: `D:/reel-engine-v2`. Tu salida es un **ReelPlan** JSON valido que el pipeline ejecuta. El motor no decide nada creativo. Reglas de oro:

1. **Una sola fuente de verdad.** Los prompts de escritura viven en `prompts/` (script.md + structure_*.md). La geometria y el registro de componentes viven en `shared/core.json` (genera `engine/_generated.py` y `remotion/src/generated.ts` con `python scripts/codegen.py`). Los umbrales de calidad viven en los validadores. NO copies esas reglas aqui ni las contradigas: si algo debe cambiar, cambia en SU archivo fuente.
2. **Tope de intentos.** Cada etapa del pipeline tiene circuit breaker (`MAX_STAGE_RETRIES=2`). Si una etapa falla 3 veces, NO insistas: para, lee `work/pipeline_state.json`, reporta la causa raiz al usuario y espera direccion. El bucle infinito de reescrituras esta prohibido.
3. **El guion se bloquea DESPUES del pase de filmabilidad y no se toca mas.** Si tras construir escenas descubres que el guion no sirve, vuelve a la etapa de guion COMPLETA (audicion + filmabilidad) y reconstruye TODAS las escenas: jamas mezcles anchors de una version del guion con el script de otra (causa #1 de planes rotos).

## Flujo

```powershell
# 1. Audicion de guion (Codex + Gemma, evaluacion ciega)
python -m engine.pipeline audition --topic "..."

# 2. Construyes el ReelPlan a mano (tu trabajo creativo) en contracts/<plan>.json

# 3. Gate del plan: validador + juez LLM + contact sheet SIN proveedores
python -m engine.pipeline plan contracts/<plan>.json
#    -> revisa VISUALMENTE work/preview/contact_sheet.png antes de seguir

# 4. Props: TTS + alignment + media + props.json (+ gates tts/plan/props)
python -m engine.pipeline props contracts/<plan>.json

# 5. Render final + QA de frames
python -m engine.pipeline render
```

Si una etapa falla: lee el error, corrige la CAUSA (plan, guion o media), y re-corre SOLO esa etapa. `python -m engine.pipeline status` muestra intentos e historial; `reset <etapa>` libera el breaker cuando la causa raiz este corregida.

**Doble gate por etapa.** Cada etapa termina con DOS jueces: el QA tecnico (`engine/qa.py`: correcto?) y el filtro ESPECTADOR (`engine/viewer_qa.py`: un humano en Instagram pararia el scroll, lo veria completo, le creeria?). Checkpoints del espectador: `script` y `motion` en plan, `broll` en props, `final` en render. Sus hallazgos (hook_sin_dolor, tono_sermon, pantalla_powerpoint, look_ia_generico, frasco_sin_etiqueta, avatar_ojos_cerrados...) son decisiones CREATIVAS: el fix es tuyo (reescribir hook, cambiar medio, otro encuadre), no del motor. Anti-varianza: corre N veces (`shared/core.json` viewer_gate) y un blocker solo bloquea si persiste en todas las corridas. Manual: `python -m engine.viewer_qa <checkpoint> <paths>`.

## Etapa de guion

1. **Referencias**: si `references/` tiene contenido, extrae observaciones de FORMATO (hook, densidad de cortes, duracion) a `meta.benchmark_notes`. Formato, nunca contenido. Vacia = sigue y dilo.
2. **Duracion por complejidad** (el rango MENOR donde cabe el mensaje): 25-35s un insight; 40-55s un mecanismo de 2-3 pasos; 60-75s caso con desarrollo.
3. **Estructura por tema** (declara en `meta.narrative_structure`): `arc` giro/mito; `case` protagonista/evento; `countdown` lista jerarquica. Si el tema admite protagonista o situacion reconocible, `case` es el default (es la unica estructura nativamente cinetica); `arc` solo si no hay caso. No uses `arc` por inercia.
4. **Audicion**: candidatos de Codex y Gemma local con el prompt de `prompts/script.md` + el bloque de estructura. Evaluacion ciega. Nada de OpenAI ni variantes del mismo modelo.
5. **Pase de filmabilidad (antes de bloquear)**: por cada frase del ganador escribe en una linea QUE SE VE nombrando **SUJETO + ACCION visible** (quien hace que). Un dato/cifra NO es respuesta valida por si solo: el dato va como overlay declarado SOBRE la accion de esa frase (la valvula "dato concreto" certificaba como filmables frases analiticas que solo cabian en stat-cards). "Un concepto/metafora/plate generica" = frase no lista. La UNICA reescritura quirurgica se gasta aqui, dirigida por filmabilidad. 2+ frases infilmables tras reescribir = pierde la audicion, pasa al siguiente candidato. Las respuestas del pase son el borrador de cada `visual_proof`. Si en construccion de escenas un beat "solo admite plate", es sintoma de que su frase fallo este pase: o es un pico presupuestado o la frase esta mal — nunca un default.

## Composicion del reel (mandato: SEMANTICA SOBRE PRECISION)

La base del reel son **personas y accion**; el texto es el acento. Un visual que DRAMATIZA la idea gana sobre un panel probatorio: la precision (cifras, frases, listas) vive en overlays declarados compuestos SOBRE la media. Los numeros viven en `shared/core.json` (`media_base`) y los validadores/jueces los aplican:

- **>=60% de las escenas body media-backed** (personas/gesto/objeto en accion). Cara hablando cuenta como media.
- **Nunca mas de 2 escenas 100%-texto seguidas** (cta/chapter cuentan como texto).
- **Golpes tipograficos (BigWordSequence/KeywordPop): max 4 por reel**, como picos, nunca escenas de relleno; BigWordSequence <=2500ms.
- **Todo plate no estructural declara `plate_last_resort_reason`** (por que NINGUNA media dramatiza ese beat). El plate es ultimo recurso, no la respuesta a un claim textual.
- **Un solo producto/objeto heroe**: declara `meta.subject_lock` (forma, envase, color; sin marca) UNA vez; props lo concatena automaticamente a TODOS los prompts de imagen. El juez de props veta el producto inconsistente entre escenas.
- **Un solo protagonista humano**: si el reel tiene una persona recurrente, declara `meta.person_lock` (edad aprox, pelo, rasgos, vestuario; sin nombre real) UNA vez; props lo concatena SOLO a los prompts que muestran una persona o sus manos (no al del telefono/diagrama). Sin esto cada gpt-image-2 inventa una cara/edad/peinado distintos y el reel se ve con 3-4 personas diferentes (el juez de props lo veta como `subject_inconsistency`).

## Construccion del plan

- Anchors: cada escena/overlay/sfx ancla a una `phrase` LITERAL del script bloqueado. Antes de declarar cualquier overlay, verifica que la frase exista con busqueda de texto exacta.
- Decision visual por pantalla: la fuente que mejor **DRAMATIZA** el beat (persona u objeto en accion) sin contradecir lo narrado; la escalera se aplica SIEMPRE, no solo ante empate: asset usuario > clip_extractor (momento real, se descarga en su MAYOR resolucion, limpiado y centrado) > pexels (personas en accion u objeto: el clip que ESCENIFICA lo narrado) > image (dramatizacion fotorealista de persona/accion; un envase/producto DEBE verse real: etiqueta legible con marca INVENTADA, nunca marca real ni texto garabateado. La PRECISION exacta del guion —cifras/frases/listas— sigue en overlays declarados, no dentro de la imagen: eso es `declared_only`, no "cero texto en la foto") > google/Omni (video generativo, ULTIMO recurso, solo declarado con generative_reason + why_real_media_failed) > none/plate (pico tipografico PRESUPUESTADO). Una foto real siempre gana a una pantalla de texto. **El motor EJECUTA esta escalera**: cuando `medium_policy` autora media (enforce/remediacion) elige la fuente mas rica que valide para la escena, y en build degrada solo si el proveedor falla (clip_extractor->pexels->image). `MEDIA_ESCALERA=image` fuerza solo-foto. Para clips reales, prefiere escenas con >=2 `visual_targets` concretos (objetos/gestos), que es de donde sale el query.
- Hook: declara `hook.mode` — `evidence` (el hook ES el momento real) o `spectacle` (generado imposible-pero-fotorealista, test OAR: Objeto+Accion+Resultado legible sin audio). Requisito transversal: si la estructura niega una creencia (arc/mito), el visual del hook MUESTRA a una persona ejecutando esa creencia; la negacion (tachado/X) es overlay declarado, jamas texto dentro de la imagen generada. Headline <=8 palabras, Cold Swipe.
- Elementos: elige por LO QUE DICE la frase, COMPUESTO SOBRE la media de la escena (overlay), no reemplazandola. Un componente tipografico solo ocupa pantalla completa en un pico presupuestado, y nunca dos beats seguidos con el mismo componente de palabra gigante. La tabla canonica de componentes vive en `shared/core.json` + los checks de contenido del validador; consulta el schema para los params obligatorios. Dos beats seguidos pueden repetir componente si el contenido lo pide.
- Caption lane: los overlays componen en la zona libre de su escena. Una lista de >3 items no es una escena: se descompone en beats secuenciales de overlay sobre media, o va al mockup del CTA. Para el caso residual permitido, declara `caption_position:"bottom"` EN esa escena (libera ~100px) en vez de encoger el contenido.
- Avatar: la cara hablando es DESEABLE. Cuando lo habilitas (no `avatar_policy:disabled`), sale **EXACTAMENTE 2 veces** (`meta.avatar_appearances`, default 2) — típicamente una en el aha y otra cerca del CTA/direccion directa. Layout canonico `split_h`: **broll o motion graphics en la mitad superior, avatar 16:9 EXACTO en la banda inferior (sin recortar la cara) y los captions en la franja del medio**. La geometria vive en `shared/core.json` (`avatar_split`). El avatar se genera y descarga en 16:9 a la mayor resolucion que entregue Kreado (`humanId=515947`, backend local: arrancalo antes con `npm start`). Cada aparicion <=5s. `frame_low`/`overlay_pip` existen pero `split_h` es el del mandato.
- Transiciones expresivas (`punch_in`/`whip`): max 3 por reel, cada una con `transition_reason`. Sin razon = cut.
- `clip.treatment` (vignette/spotlight/duotone_brand): con intencion concreta, nunca como maquillaje.
- CTA: la palabra del boton aparece literal al final del script. Si promete recurso: resource_title + resource_points + mockup_type.

## Limite honesto

Tu garantizas un plan coherente y con intencion; el motor garantiza render tecnico y gates; la retencion real se valida publicando. Cuando el circuit breaker corta, la respuesta correcta es diagnostico + propuesta al usuario, no otra vuelta.
