#!/bin/bash
# Prueba el detector de voz de la app compilada: con silencio, ruido, pitido, teclas o voz lejana no debe salir nada; con voz cerca, sí.
# No usa micro, altavoces ni red. Uso: ./build.sh && ./probar.sh
set -e
BIN="$(cd "$(dirname "$0")" && pwd)/build/WhisperTool.app/Contents/MacOS/WhisperTool"
SON="$(cd "$(dirname "$0")" && pwd)/sonidos"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; cd "$T"
afconvert -f WAVE -d LEI16@16000 -c 1 "$SON/beep_start.wav" pitido.wav
i=0; for t in "Sí" "No" "Continúa" "Abre el calendario y mira qué tengo mañana"; do say -v Monica -o $i.aiff "$t"; afconvert -f WAVE -d LEI16@16000 -c 1 $i.aiff voz$i.wav; i=$((i+1)); done
python3 - <<'P'
import wave,array,random,math,glob
random.seed(1)
def leer(n):
    with wave.open(n) as f: return [v/32768 for v in array.array('h',f.readframes(f.getnframes()))]
def escribir(n,x):
    with wave.open(n,'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(array.array('h',[int(max(-1,min(1,v))*32767) for v in x]).tobytes())
ruido=lambda s,a:[random.gauss(0,a) for _ in range(int(16000*s))]
escribir('no_ceros.wav',[0]*16000)
for a in (.0005,.004,.01):
    for s in (.6,3): escribir(f'no_ruido_{a}_{s}.wav',ruido(s,a))
p=leer('pitido.wav')
for g in (.05,.5):
    x=ruido(2,.001)
    for i,v in enumerate(p): x[800+i]+=v*g
    escribir(f'no_pitido_{g}.wav',x)
x=ruido(2,.001)
for k in (100,9000,15000,30000):
    for i in range(200): x[k+i]+=random.gauss(0,.15)*(1-i/200)
escribir('no_teclas.wav',x)
for n in sorted(glob.glob('voz*.wav')):
    y=leer(n)
    for g in (.02,.75,1): escribir(f"{'no_lejos' if g<.1 else 'si'}_{n[3]}_{g}.wav",[v*g+random.gauss(0,.001) for v in [0]*4000+y+[0]*4000])
P
"$BIN" --voz no_*.wav si_*.wav | awk '/ no_/&&/VOZ/||/ si_/&&!/VOZ/{print "✗ "$0;m=1;next}{print "✓ "$0} END{exit m}'
