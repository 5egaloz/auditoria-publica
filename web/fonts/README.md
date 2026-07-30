# Tipografías

**IBM Plex Sans** e **IBM Plex Mono**, servidas desde este repositorio en vez de
desde un CDN de terceros.

## Por qué locales

El sitio se sostiene en un argumento: *no confíes en nosotros, recalcula los
hashes*. Cargar las fuentes desde `fonts.gstatic.com` metía una dependencia de
terceros —y una petición que revela la visita a un tercero— en una página cuya
propuesta es justamente no depender de nadie. Servirlas desde acá cierra eso, y
además la página deja de romperse si ese CDN cae o está bloqueado.

## Archivos

| Archivo | Contenido |
|---|---|
| `ibm-plex-sans-latin.woff2` | Plex Sans, subset `latin`. Es **fuente variable**: un solo archivo cubre los pesos 400, 500 y 600. |
| `ibm-plex-sans-latin-ext.woff2` | Plex Sans, subset `latin-ext`. |
| `ibm-plex-mono-400-latin.woff2` | Plex Mono 400, subset `latin`. |
| `ibm-plex-mono-400-latin-ext.woff2` | Plex Mono 400, subset `latin-ext`. |
| `ibm-plex-mono-500-latin.woff2` | Plex Mono 500, subset `latin`. |
| `ibm-plex-mono-500-latin-ext.woff2` | Plex Mono 500, subset `latin-ext`. |

130 KB en total. El subset `latin` ya trae los acentos del español (á é í ó ú ñ ü);
`latin-ext` va aparte y el navegador **solo lo descarga si aparece un carácter que
lo necesite**, por el `unicode-range` de cada `@font-face`.

Origen: subsets woff2 de Google Fonts (Plex Sans v23, Plex Mono v20).

## Licencia

SIL Open Font License 1.1 — ver `LICENSE.txt`. Reserved Font Name: "Plex".
La OFL permite redistribuir los archivos junto al proyecto; por eso la licencia
viaja en esta misma carpeta.
