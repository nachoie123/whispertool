#!/bin/bash
# Doble clic para publicar WhisperTool en tu GitHub.
cd "$HOME/whispertool" || exit 1
echo "======================================================"
echo "   Publicando WhisperTool en GitHub (nachoie123)"
echo "======================================================"
echo
echo "Cuando te lo pida, escribe EXACTAMENTE esto:"
echo
echo "   Username for 'https://github.com':   nachoie123"
echo "   Password for 'https://...':          <PEGA TU TOKEN>"
echo
echo "   (Al pegar el token NO se verá nada en pantalla. Es normal."
echo "    Pega con Cmd+V y pulsa Enter.)"
echo
echo "------------------------------------------------------"
git push mine main --force
RC=$?
echo "------------------------------------------------------"
echo
if [ $RC -eq 0 ]; then
  echo "LISTO. Tu repositorio ya esta publicado en:"
  echo "   https://github.com/nachoie123/whispertool"
else
  echo "Algo fallo (codigo $RC). Revisa el usuario y el token, y vuelve a hacer doble clic."
fi
echo
read -n 1 -s -r -p "Pulsa una tecla para cerrar esta ventana..."
echo
