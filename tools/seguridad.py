#!/usr/bin/env python3
"""Chequeo de seguridad de dist/WhisperTool.app, ejecutado de verdad. Escribe tools/seguridad.md
(no docs/: esa carpeta es la web publicada en GitHub Pages).

  .venv/bin/python tools/seguridad.py dist/WhisperTool.app

(a) Datos personales y claves: abre TODO el paquete (también el archivo comprimido de Python que va
    dentro del ejecutable y los .zip) y cuenta cuántas veces aparece cada línea de
    ~/.config/personal-scan/patterns.txt (correos, teléfono, dirección y claves reales de Nacho),
    la ruta de su carpeta personal y cualquier cosa con forma de clave de API. Nunca imprime los
    valores: solo el número de la línea y cuántas veces sale.
(b) Ficheros que no deben ir: config.json (lleva las claves del usuario), *.db, *.sqlite, .env, *.key, CVs.
(c) Info.plist: micrófono con su texto, identificador, solo arm64, macOS mínimo, sin LSUIElement.
(d) Arquitecturas de cada binario (lipo -archs): todos con arm64 (mlx no existe para Intel).
(e) Selftest de la app empaquetada (main.py --selftest, sin atajo, sin micro, sin teclas): imports nativos,
    GPU, config 600, texto, transcripción con `say`, descarga con progreso, ventana y cápsula
    (capturas en build/) y que al cerrar no queda ningún proceso vivo.
"""
import json
import marshal
import os
import plistlib
import re
import subprocess
import sys
import time
import zipfile
import zlib
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PATTERNS = Path.home() / ".config" / "personal-scan" / "patterns.txt"
MACHO = (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe")


def bundle_blobs(app: Path):
    """(nombre, bytes) de cada fichero del .app, con los archivos de PyInstaller abiertos."""
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader
    for f in app.rglob("*"):
        if not f.is_file() or f.is_symlink():
            continue
        data = f.read_bytes()
        yield str(f.relative_to(app)), data
        if f.suffix == ".zip":
            with zipfile.ZipFile(f) as z:
                for n in z.namelist():
                    yield f"{f.name}!{n}", z.read(n)
        if f.parent.name == "MacOS":
            try:
                ca = CArchiveReader(str(f))
            except Exception:
                continue
            for name in ca.toc:
                try:
                    blob = ca.extract(name)
                except Exception:
                    continue
                yield f"exe!{name}", blob or b""
                if name.endswith(".pyz") or name.startswith("PYZ"):
                    tmp = HERE / "build" / "_pyz.tmp"
                    tmp.write_bytes(blob)
                    z = ZlibArchiveReader(str(tmp))
                    for mod in z.toc:
                        try:
                            code = z.extract(mod, raw=True)
                        except TypeError:
                            code = z.extract(mod)
                        if isinstance(code, bytes):
                            try:
                                code = zlib.decompress(code)
                            except zlib.error:
                                pass
                            yield f"pyz!{mod}", code
                        else:
                            yield f"pyz!{mod}", marshal.dumps(code) if code else b""
                    tmp.unlink()


def secrets_to_find():
    """{etiqueta: patrón bytes o regex}. Las etiquetas nunca llevan el valor."""
    s = {}
    if PATTERNS.exists():
        lines = [l.strip() for l in PATTERNS.read_text().splitlines()]
        for i, l in enumerate(lines, 1):
            if l and not l.startswith("#"):
                s[f"patterns.txt, línea {i}"] = l.encode()
    s[f"ruta de la carpeta personal (/Users/{Path.home().name})"] = str(Path.home()).encode()
    s["clave con forma de Gemini/Google (AIza…)"] = re.compile(rb"AIza[0-9A-Za-z_\-]{35}")
    s["clave con forma de OpenAI (sk-…)"] = re.compile(rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{20,}")
    s["clave de Anthropic (sk-ant-)"] = b"sk-ant-"
    s["token de GitHub (ghp_)"] = re.compile(rb"ghp_[A-Za-z0-9]{20,}")
    s["clave de ElevenLabs (xi-api)"] = b"xi-api"
    return s


DATAFILES = re.compile(r"(^|[/!])(config\.json|\.env|[^/]*\.(db|sqlite3?|key)|[^/]*(cv|curriculum|resume)[^/]*\.pdf)$",
                       re.IGNORECASE)


def scan(app):
    pats = secrets_to_find()
    hits = {k: {} for k in pats}
    datafiles, files, total = [], 0, 0
    for name, data in bundle_blobs(app):
        files += 1
        total += len(data)
        if DATAFILES.search(name):
            datafiles.append(name)
        for label, p in pats.items():
            n = len(p.findall(data)) if hasattr(p, "findall") else data.count(p)
            if n:
                hits[label][name] = n
    return files, total, hits, datafiles, len([k for k in pats if k.startswith("patterns.txt")])


def archs(app):
    out = {}
    for f in app.rglob("*"):
        if f.is_file() and not f.is_symlink():
            with open(f, "rb") as fh:
                if fh.read(4) not in MACHO:
                    continue
            r = subprocess.run(["lipo", "-archs", str(f)], capture_output=True, text=True)
            if r.returncode == 0:
                out[str(f.relative_to(app))] = r.stdout.strip()
    return out


def selftest(app):
    """Lanza la app empaquetada en modo selftest, captura la ventana y la cápsula y espera a que se cierre."""
    out = HERE / "build" / "selftest-app.json"
    out.unlink(missing_ok=True)
    exe = app / "Contents" / "MacOS" / "WhisperTool"
    env = dict(os.environ, WT_SELFTEST_HOLD="6")
    log = open(HERE / "build" / "selftest-app.log", "w")
    t0 = time.time()
    p = subprocess.Popen([str(exe), "--selftest", str(out)], env=env, stdout=log, stderr=log)
    shots = {}
    while p.poll() is None and time.time() - t0 < 600:
        time.sleep(0.5)
        if shots or not out.exists():
            continue
        try:
            ui = json.loads(out.read_text()).get("ui") or {}
        except ValueError:
            continue
        if ui.get("windows") and not ui.get("closed"):
            time.sleep(1.5)  # que la cápsula ya esté pintada
            for w in ui["windows"]:
                if w["number"] > 0:  # la cápsula aún sale invisible en ese instante: se pinta en el siguiente tick
                    kind = "ventana" if "WhisperTool" in w["title"] else "capsula"
                    dest = HERE / "build" / f"captura-{kind}.png"
                    r = subprocess.run(["screencapture", "-x", "-o", f"-l{w['number']}", str(dest)],
                                       capture_output=True)
                    shots[kind] = str(dest.relative_to(HERE)) if r.returncode == 0 and dest.exists() else "falló"
    if p.poll() is None:
        p.kill()
    time.sleep(2)
    # ¿Queda algo vivo del paquete? (p. ej. el resource tracker de multiprocessing relanzando la app)
    left = subprocess.run(["pgrep", "-f", str(app / "Contents" / "MacOS")], capture_output=True, text=True).stdout.split()
    r = json.loads(out.read_text()) if out.exists() else {"exception": "la app no escribió el resultado"}
    r["_exit"], r["_secs"], r["_shots"], r["_orphans"] = p.returncode, round(time.time() - t0, 1), shots, len(left)
    return r


def main():
    app = Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "dist" / "WhisperTool.app").resolve()
    files, size, hits, datafiles, npat = scan(app)
    ar = archs(app)
    no_arm = {k: v for k, v in ar.items() if "arm64" not in v.split()}
    fat = {k: v for k, v in ar.items() if v != "arm64"}
    pl = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    sign = subprocess.run(["codesign", "-dv", str(app)], capture_output=True, text=True).stderr
    st = selftest(app)

    imp = st.get("imports") or {}
    tp = (st.get("text_processor") or {}).get("out", "")
    words = re.findall(r"\w+", tp.lower())
    dl, cpu, mlx, ui = st.get("download") or {}, st.get("cpu") or {}, st.get("mlx") or {}, st.get("ui") or {}
    mlx_cached = "skip" not in mlx

    ok_a = not any(hits.values()) and npat > 0
    ok_b = not datafiles
    ok_c = (bool(pl.get("NSMicrophoneUsageDescription")) and pl.get("CFBundleIdentifier") == "com.nachosanbenito.whispertool"
            and pl.get("LSArchitecturePriority") == ["arm64"] and pl.get("LSMinimumSystemVersion") == "14.0"
            and pl.get("NSHighResolutionCapable") is True and "LSUIElement" not in pl)
    ok_d = bool(ar) and not no_arm
    ok_imp = bool(imp) and all(v == "ok" for v in imp.values())
    ok_gpu = str((st.get("mlx_gpu") or {}).get("device", "")).startswith("Device(gpu") and st["mlx_gpu"].get("sum") == 12.0
    ok_cfg = st.get("config") == {"mode": "0o600", "roundtrip": True}
    ok_txt = ("um" not in words and "mike" in words and "john" not in words and "3" in words and "2" not in words
              and "period" not in words and "." in tp and st.get("email_mode") == [True, "hola Ana, nos vemos mañana"])
    ok_mlx = mlx_cached and "test" in mlx.get("text", "").lower() and "dictation" in mlx.get("text", "").lower()
    ok_dl = dl.get("progress_calls", 0) > 0 and "model.bin" in (dl.get("files") or [])
    ok_cpu = "test" in cpu.get("text", "").lower()
    ok_ui = (ui.get("model") in ("mlx", "skipped") and ui.get("status_at_close") == "Ready" and ui.get("overlay_visible") is True
             and ui.get("closed") is True and "WhisperTool" in ui.get("title", "")
             and st.get("_shots", {}).get("ventana", "falló") != "falló")
    ok_exit = st.get("_exit") == 0 and st.get("_orphans") == 0
    mark = lambda b: "OK" if b else "FALLA"

    L = ["# Chequeo de seguridad de WhisperTool.app", "",
         f"Generado por `tools/seguridad.py` el {datetime.now():%Y-%m-%d %H:%M} sobre `{app.relative_to(HERE)}`"
         f" ({size / 1e6:.0f} MB descomprimidos, {files} ficheros revisados).",
         "Todo lo de abajo es salida real de este script, no texto escrito a mano.", "",
         "| Prueba | Resultado |", "|---|---|",
         f"| (a) Sin datos personales ni claves de API en el paquete ({npat} líneas de patterns.txt + ruta personal + 5 formas de clave) | {mark(ok_a)} |",
         f"| (b) Sin config.json, bases de datos, .env, .key ni CVs dentro | {mark(ok_b)} |",
         f"| (c) Info.plist: micrófono explicado, com.nachosanbenito.whispertool, solo arm64, macOS 14+, sin LSUIElement | {mark(ok_c)} |",
         f"| (d) Todos los binarios tienen arm64 ({len(ar)} binarios) | {mark(ok_d)} |",
         f"| (e1) Importa todo lo nativo ({len(imp)} módulos) | {mark(ok_imp)} |",
         f"| (e2) MLX calcula en la GPU (kernels Metal dentro del paquete) | {mark(ok_gpu)} |",
         f"| (e3) config.json se crea con permisos 600 | {mark(ok_cfg)} |",
         f"| (e4) text_processor y modo email dan el texto esperado | {mark(ok_txt)} |",
         f"| (e5) Transcribe en la GPU (large-v3-turbo) una frase en inglés hecha con `say` | "
         + (mark(ok_mlx) if mlx_cached else "modelo no en caché (no se prueba)") + " |",
         f"| (e6) Primera vez: descarga un modelo de Hugging Face avisando del progreso | {mark(ok_dl)} |",
         f"| (e7) Transcribe en la CPU (faster-whisper, el plan B) | {mark(ok_cpu)} |",
         f"| (e8) Abre la ventana y la cápsula, carga el modelo y queda en «Ready» | {mark(ok_ui)} |",
         f"| (e9) Al cerrar, sale con código 0 y no deja procesos vivos | {mark(ok_exit)} |",
         "", "## (a) Datos personales y claves", "",
         "Se buscan los valores exactos en cada fichero, en cada módulo del archivo de Python del ejecutable y"
         " dentro de los .zip; no se imprimen, solo cuántas veces aparecen:", ""]
    for k, v in hits.items():
        L.append(f"- {k}: **{sum(v.values())}**" + (f" en {', '.join(list(v)[:5])}" if v else ""))
    L += ["", "## (b) Ficheros de datos", "", f"Encontrados: {datafiles or 'ninguno'}"
          " (`config.example.json` no va dentro: el usuario empieza con la config por defecto).", "",
          "## (c) Info.plist", "", "```"]
    L += [f"{k}: {pl.get(k)!r}" for k in ("CFBundleName", "CFBundleIdentifier", "CFBundleShortVersionString",
                                           "NSMicrophoneUsageDescription", "NSHighResolutionCapable",
                                           "LSMinimumSystemVersion", "LSArchitecturePriority", "LSUIElement")]
    L += ["```", "", "Firma: " + " · ".join(l for l in sign.splitlines() if l.startswith(("Signature", "Identifier", "TeamIdentifier"))),
          "", "## (d) Arquitecturas", "",
          f"{len(ar)} binarios Mach-O; sin arm64: {no_arm or 'ninguno'}; con más de una arquitectura: {len(fat)}"
          + (f" ({', '.join(list(fat)[:5])})" if fat else "") + ".", ""]
    L += [f"- `{k}`: {v}" for k, v in sorted(ar.items()) if "MacOS" in k or "Python" in k or "libmlx" in k or "ctranslate2" in k][:8]
    L += ["", "## (e) Selftest de la app empaquetada", "",
          f"`Contents/MacOS/WhisperTool --selftest` (sin atajo global, sin micrófono, sin pulsar ni pegar nada),"
          f" {st.get('_secs')} s, código de salida {st.get('_exit')}, procesos del paquete vivos después: {st.get('_orphans')}.", "",
          f"- Imports: {json.dumps(imp)}",
          f"- GPU: {st.get('mlx_gpu')}; PortAudio: {st.get('portaudio')}",
          f"- Config en carpeta temporal: {st.get('config')}; la de verdad va en `{st.get('data_dir')}`",
          f"- Texto: «{(st.get('text_processor') or {}).get('in')}» → «{tp}»",
          f"- Modo email: {st.get('email_mode')}",
          f"- Audio de `say`: {st.get('say')}",
          f"- GPU (MLX large-v3-turbo): {mlx}",
          f"- Descarga (caché temporal, modelo pequeño): {dl}",
          f"- CPU (faster-whisper tiny): {cpu}",
          f"- Ventana: {json.dumps(ui, ensure_ascii=False)}",
          f"- Capturas: {st.get('_shots')}"]
    if st.get("exception"):
        L += ["", "## Error en el selftest", "", "```", st["exception"], "```"]
    (HERE / "tools" / "seguridad.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[5:22]))
    sys.exit(0 if all((ok_a, ok_b, ok_c, ok_d, ok_imp, ok_gpu, ok_cfg, ok_txt, ok_dl, ok_cpu, ok_ui, ok_exit))
             and (ok_mlx or not mlx_cached) else 1)


if __name__ == "__main__":
    main()
