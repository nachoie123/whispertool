# Chequeo de seguridad de WhisperTool.app

Generado por `tools/seguridad.py` el 2026-10-03 19:49 sobre `dist/WhisperTool.app` (605 MB descomprimidos, 3476 ficheros revisados).
Todo lo de abajo es salida real de este script, no texto escrito a mano.

| Prueba | Resultado |
|---|---|
| (a) Sin datos personales ni claves de API en el paquete (13 líneas de patterns.txt + ruta personal + 5 formas de clave) | OK |
| (b) Sin config.json, bases de datos, .env, .key ni CVs dentro | OK |
| (c) Info.plist: micrófono explicado, com.nachosanbenito.whispertool, solo arm64, macOS 14+, sin LSUIElement | OK |
| (d) Todos los binarios tienen arm64 (284 binarios) | OK |
| (e1) Importa todo lo nativo (17 módulos) | OK |
| (e2) MLX calcula en la GPU (kernels Metal dentro del paquete) | OK |
| (e3) config.json se crea con permisos 600 | OK |
| (e4) text_processor y modo email dan el texto esperado | OK |
| (e5) Transcribe en la GPU (large-v3-turbo) una frase en inglés hecha con `say` | OK |
| (e6) Primera vez: descarga un modelo de Hugging Face avisando del progreso | OK |
| (e7) Transcribe en la CPU (faster-whisper, el plan B) | OK |
| (e8) Abre la ventana y la cápsula, carga el modelo y queda en «Ready» | OK |
| (e9) Al cerrar, sale con código 0 y no deja procesos vivos | OK |

## (a) Datos personales y claves

Se buscan los valores exactos en cada fichero, en cada módulo del archivo de Python del ejecutable y dentro de los .zip; no se imprimen, solo cuántas veces aparecen:

- patterns.txt, línea 1: **0**
- patterns.txt, línea 2: **0**
- patterns.txt, línea 3: **0**
- patterns.txt, línea 4: **0**
- patterns.txt, línea 5: **0**
- patterns.txt, línea 6: **0**
- patterns.txt, línea 7: **0**
- patterns.txt, línea 8: **0**
- patterns.txt, línea 9: **0**
- patterns.txt, línea 10: **0**
- patterns.txt, línea 11: **0**
- patterns.txt, línea 12: **0**
- patterns.txt, línea 13: **0**
- ruta de la carpeta personal (/Users/nachosanbenito): **0**
- clave con forma de Gemini/Google (AIza…): **0**
- clave con forma de OpenAI (sk-…): **0**
- clave de Anthropic (sk-ant-): **0**
- token de GitHub (ghp_): **0**
- clave de ElevenLabs (xi-api): **0**

## (b) Ficheros de datos

Encontrados: ninguno (`config.example.json` no va dentro: el usuario empieza con la config por defecto).

## (c) Info.plist

```
CFBundleName: 'WhisperTool'
CFBundleIdentifier: 'com.nachosanbenito.whispertool'
CFBundleShortVersionString: '1.0.0'
NSMicrophoneUsageDescription: 'WhisperTool listens only while you hold the hotkey, to turn your speech into text. Transcription happens on this Mac: your audio never leaves it.'
NSHighResolutionCapable: True
LSMinimumSystemVersion: '14.0'
LSArchitecturePriority: ['arm64']
LSUIElement: None
```

Firma: Identifier=com.nachosanbenito.whispertool · Signature=adhoc · TeamIdentifier=not set

## (d) Arquitecturas

284 binarios Mach-O; sin arm64: ninguno; con más de una arquitectura: 0.

- `Contents/Frameworks/Python.framework/Versions/3.12/Python`: arm64
- `Contents/Frameworks/ctranslate2/__dot__dylibs/libctranslate2.4.8.2.dylib`: arm64
- `Contents/Frameworks/ctranslate2/_ext.cpython-312-darwin.so`: arm64
- `Contents/Frameworks/mlx/lib/libmlx.dylib`: arm64
- `Contents/MacOS/WhisperTool`: arm64

## (e) Selftest de la app empaquetada

`Contents/MacOS/WhisperTool --selftest` (sin atajo global, sin micrófono, sin pulsar ni pegar nada), 26.9 s, código de salida 0, procesos del paquete vivos después: 0.

- Imports: {"mlx.core": "ok", "mlx_whisper": "ok", "faster_whisper": "ok", "ctranslate2": "ok", "onnxruntime": "ok", "av": "ok", "sounddevice": "ok", "pynput.keyboard": "ok", "pyautogui": "ok", "pyperclip": "ok", "AppKit": "ok", "Quartz": "ok", "AVFoundation": "ok", "HIServices": "ok", "huggingface_hub": "ok", "hf_xet": "ok", "certifi": "ok"}
- GPU: {'device': 'Device(gpu, 0)', 'sum': 12.0}; PortAudio: PortAudio V19.7.0-devel, revision unknown
- Config en carpeta temporal: {'mode': '0o600', 'roundtrip': True}; la de verdad va en `/Users/nachosanbenito/Library/Application Support/WhisperTool`
- Texto: «um so I want to meet at 2 actually 3 period send it to John I mean Mike» → «So I want to meet at 3. send it to Mike»
- Modo email: [True, 'hola Ana, nos vemos mañana']
- Audio de `say`: {'phrase': 'Hello, this is a quick test of the dictation tool.', 'secs': 2.9}
- GPU (MLX large-v3-turbo): {'text': 'Hello, this is a quick test of the dictation tool', 'language': 'en', 'secs': 2.4}
- Descarga (caché temporal, modelo pequeño): {'repo': 'Systran/faster-whisper-tiny', 'secs': 9.0, 'files': ['.gitattributes', 'README.md', 'config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt'], 'progress_calls': 80, 'progress_mb': [0.0, 8.1, 18.9, 26.8, 37.1, 47.9, 58.5, 69.2, 78.2]}
- CPU (faster-whisper tiny): {'text': 'Hello, this is a quick test of the dictation tool.', 'language': 'en', 'secs': 0.4}
- Ventana: {"model": "mlx", "load_secs": 1.8, "title": "WhisperTool v1.0.0 (by FuturMinds)", "windows": [{"title": "WhisperTool v1.0.0 (by FuturMinds)", "number": 29962, "visible": true}, {"title": "", "number": 29963, "visible": true}], "status_at_close": "Ready", "overlay_visible": true, "closed": true}
- Capturas: {'ventana': 'build/captura-ventana.png', 'capsula': 'build/captura-capsula.png'}
