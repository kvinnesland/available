# Beslutninger

Valg tatt der specen var åpen eller måtte presiseres.

1. **Gjesterom ved heldagshendelser.** Specen sier at `Gjest:`-hendelser blokkerer natta, men ikke hvilke netter en heldagshendelse dekker. Folk skriver oftest ankomst til avreise, så «Gjest: Mamma» fre–søn gir fredag og lørdag natt. En endagshendelse gir én natt. Med klokkeslett brukes kjernenatta (00–06). Reglene i 4.2 er uendret.
2. **Kilde-nøkler** er `shared1`, `shared2` osv. Visningsnavn i admin er «Felles 1».
3. **Tomme ICS-variabler** gir en helt ledig kalender, slik at første deploy kan gjøres uten URL-er (spec 13).
4. **Kun https-URL-er** godtas for ICS. Appen nekter å starte på `http://`.
5. **Tilgangsloggen i uvicorn er slått av** (`--no-access-log`), fordi den logger hele URL-en med `?k=<VISITOR_KEY>`. Feilmeldinger fra henting logger bare kildenøkkel og feiltype, aldri URL eller tittel.
6. **Statiske filer** serveres ikke som mappe. Bare `/static/modes.js` er åpen; `index.html` krever nøkkel og `admin.html` krever innlogging. FastAPIs `/docs` og `/openapi.json` er slått av.
7. **`Cache-Control: no-store`** på alle svar, i tillegg til headerne i specen, fordi nøkkelen står i URL-en.
8. **Admin-innlogging** gir 401 med `WWW-Authenticate` (nødvendig for at nettleseren skal vise innloggingsboks), ikke 404 som for besøkende.
9. **`/api/admin/nights?from=&to=`**: `to` er eksklusiv, maks 400 netter. Uten parametere vises inneværende måned.
10. **Cache på disk** lagrer parsede hendelser per kilde (ikke URL-er) med filrettighet 600, skrevet atomisk. Etter omstart brukes cachen til første vellykkede henting.
11. **Klient-IP** for rate limiting er første verdi i `X-Forwarded-For` (Traefik), ellers socket-adressen. Uten proxy foran kan headeren forfalskes; det er akseptert siden appen alltid kjører bak Traefik i Coolify.
12. **Aria-label** på dagcellene er «Natten fra torsdag 5. november 2026 til fredag 6. november, ikke ledig». Spec-eksempelet «Natt til lørdag 13.» er tvetydig på norsk (betyr natta *før* lørdag), så formuleringen er gjort entydig.
13. **Avreisedag** kan velges én dag etter siste natt i horisonten.
14. **Flytende tider** (uten tidssone) tolkes som `TZ_LOCAL`.
15. **Transitive avhengigheter** som følger med de tillatte pakkene: `opentelemetry-api` og `annotated-doc` (via fastapi), `x-wr-timezone` (via recurring-ical-events), pluss pydantic, starlette, anyio m.fl. Ingen er lagt til direkte.
16. **Python-versjon**: Dockerfile bruker `python:3.12-slim` (tag, ikke digest). Vurder å feste til digest når imaget er bygget første gang.
12. **Kun felleskalenderen.** Håvards og Mariannes personlige kalendere (`ICS_HAVARD`, `ICS_MARIANNE`) er fjernet. Alle vanlige hendelser i `ICS_SHARED` gjør at vi er borte (`home=false`), `Gjest:`/`Besøk:` gjør gesterommet opptatt (`room=false`). API-et returnerer `{date, home, room}`, og en natt er ledig når begge er `true`. Valget «Hvem må være hjemme?» i frontend er fjernet.
