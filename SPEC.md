# SPEC: «Kom på besøk» – besøkskalender for Tromsø

Bygg hele applikasjonen beskrevet under i én omgang. Ikke spør om avklaringer underveis; der noe er uklart, velg det enkleste alternativet som oppfyller akseptansekriteriene og noter valget i `DECISIONS.md`. Hvis repoet har en `SECURITY.md`, gjelder sikkerhetskravene der i tillegg til denne specen. Finnes det en `CLAUDE.md` som ber deg stille spørsmål eller gå gjennom sjekklister før du bygger, skal du ikke gjøre det: denne specen er bestillingen, og alt nødvendig står her.

## 1. Formål

Venner og familie skal kunne se hvilke netter det passer å komme på besøk til oss i Tromsø. Besøk varer flere dager og innebærer overnatting, så **enheten i systemet er netter, ikke klokkeslett.** Besøkende ser bare «ledig / ikke ledig», aldri hva som står i kalenderne våre.

## 2. Brukere

- **Besøkende** (venner/familie): åpner en hemmelig lenke, ser ledige netter, velger periode, sender forespørsel på e-post.
- **Eiere** (Håvard og Marianne): har i tillegg en passordbeskyttet admin-side som viser *hvorfor* en natt er blokkert (hendelsestittel og kilde), for å kunne stole på og feilsøke systemet.

## 3. Kalenderkilder

Én kilde: felleskalenderen, konfigurert som hemmelig iCal-URL fra Google Kalender (Innstillinger → kalenderen → «Integrer kalender» → «Hemmelig adresse i iCal-format») i env-variabelen `ICS_SHARED`. Den kan inneholde flere URL-er separert med komma, og er valgfri ved første deploy.

URL-ene er hemmeligheter: de skal kun finnes i env, aldri logges, aldri sendes til frontend, aldri committes. Ikke bruk OAuth eller Google API i v1.

## 4. Tilgjengelighetslogikk (kjernen – test grundig)

All tidsberegning skjer i tidssonen `Europe/Oslo` (konfigurerbar via `TZ_LOCAL`). Bruk `zoneinfo`.

### 4.1 Natt
Natt `D` = natta som starter dato `D` og slutter morgenen `D+1`.
- **Kveldsvindu:** `D 18:00` → `D+1 00:00`
- **Kjernenatt:** `D+1 00:00` → `D+1 06:00`
- **Morgenvindu:** `D+1 06:00` → `D+1 09:00`
- Hele nattvinduet = `D 18:00` → `D+1 09:00`. Klokkeslettene er konfigurerbare (`NIGHT_START=18:00`, `NIGHT_END=09:00`).

### 4.2 Når blokkerer en hendelse en person for natt D?
Evaluer reglene i rekkefølge; første treff avgjør:

1. Tittel inneholder `#hjemme` (case-insensitivt) → **ignoreres alltid.**
2. Hendelsen har status `CANCELLED` → ignoreres.
3. Tittel inneholder `#borte` → blokkerer hvis den overlapper hele nattvinduet.
4. **Heldagshendelse** (DTSTART er dato uten klokkeslett), inkludert flerdagers → blokkerer hvis den overlapper hele nattvinduet. (En heldagshendelse på fredag blokkerer dermed torsdag natt og fredag natt. Dette er bevisst: verten må være hjemme både kveld og morgen.)
5. **Tidsbestemt hendelse** → blokkerer bare hvis den overlapper kjernenatta (`D+1 00:00–06:00`). En middag 19–22 blokkerer ikke; en nattevakt eller sen flyreise gjør det.

Ignorer `TRANSP`/«Ledig/Opptatt»-feltet helt. Google setter heldagshendelser til «Ledig» som standard, så feltet er upålitelig her.

### 4.3 Gjentakende hendelser
Gjentakende hendelser (RRULE, EXDATE, RECURRENCE-ID-overstyringer) skal ekspanderes korrekt. Bruk biblioteket `recurring-ical-events` oppå `icalendar`.

### 4.4 Felleskalenderen
- Hendelser i `ICS_SHARED` som starter med `Gjest:` eller `Besøk:` (case-insensitivt) betyr at **gjesterommet er opptatt**. De blokkerer ikke `home`.
- Alle andre hendelser i `ICS_SHARED` følger reglene i 4.2 og betyr at vi ikke er hjemme (`home=false`).

### 4.5 Resultat per natt
For hver natt fra i dag til `HORIZON_DAYS` (standard 365) frem beregnes:

```json
{ "date": "2026-12-12", "home": true, "room": true }
```
- `home` = vi er hjemme, `room` = gjesterom ledig.
- En natt er ledig for besøk når `home && room`. Beregnes i frontend.

Netter før i dag vises ikke som ledige.

## 5. Arkitektur

- **Backend:** Python 3.12, FastAPI, uvicorn, httpx.
- **Frontend:** én statisk `index.html` med inline CSS og vanilla JS. Ingen byggesteg, ingen rammeverk, ingen eksterne CDN-er.
- **Lagring:** ingen database. Beregnet tilgjengelighet holdes i minnet og i tillegg skrives til `data/cache.json` slik at siste kjente resultat overlever omstart.
- **Henting:** bakgrunnsjobb henter alle ICS-URL-er hvert `REFRESH_MINUTES` (standard 15). Feiler én kilde, beholdes forrige resultat for den kilden og feilen logges (uten URL). Timeout 20 s per kilde.
- **Deploy:** Docker-image for Coolify på Hetzner. Ikke-root bruker i containeren. Healthcheck på `/healthz`.

### Avhengigheter
Kun disse (fest versjoner, bruk `pip-compile --generate-hashes` og installer med `--require-hashes`). Verifiser at hvert pakkenavn finnes på PyPI før bruk; ikke legg til andre pakker uten å notere hvorfor i `DECISIONS.md`.
- `fastapi`, `uvicorn`, `httpx`, `icalendar`, `recurring-ical-events`, `tzdata`
- Dev: `pytest`, `freezegun`

### Filstruktur
```
app/
  main.py          # FastAPI-app, ruter, oppstart av bakgrunnsjobb
  config.py        # leser env, validerer
  fetch.py         # henter ICS
  availability.py  # ren logikk: hendelser -> netter (ingen I/O)
  static/index.html
  static/admin.html
tests/
  fixtures/*.ics
  test_availability.py
  test_api.py
Dockerfile
.env.example
requirements.in / requirements.txt
DECISIONS.md
README.md          # norsk: oppsett, hvordan finne iCal-adressen, deploy i Coolify
```

## 6. API

| Metode | Sti | Beskyttelse | Svar |
|---|---|---|---|
| GET | `/` | `?k=<VISITOR_KEY>` | `index.html` |
| GET | `/api/nights` | `?k=<VISITOR_KEY>` | `{ "updated_at": ISO, "nights": [ ... ] }` (format i 4.5) |
| GET | `/admin` | HTTP Basic (`ADMIN_USER`/`ADMIN_PASSWORD`) | `admin.html` |
| GET | `/api/admin/nights?from=&to=` | Basic | Som over, pluss `reasons: [{person, source, title, rule}]` per natt |
| POST | `/api/admin/refresh` | Basic | Tvinger ny henting |
| GET | `/healthz` | ingen | `{"ok": true, "last_success": ISO}` |

Feil `k` eller manglende `k` → 404 (ikke 401, for ikke å avsløre at siden finnes). Sammenlign nøkler med `hmac.compare_digest`.

`/api/nights` skal **aldri** inneholde titler, beskrivelser, steder eller annen hendelsesdata.

## 7. Sikkerhet

- Security headers: `Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` (viktig, siden nøkkelen ligger i URL-en), `X-Robots-Tag: noindex, nofollow`.
- `robots.txt` som nekter alt.
- Enkel rate limiting per IP i minnet: maks 60 forespørsler/min mot `/api/*`, maks 10 feilede admin-innlogginger/time.
- Logger skal aldri inneholde ICS-URL-er, `VISITOR_KEY` eller hendelsestitler (unntatt admin-endepunktet som returnerer dem til autentisert bruker).
- Appen skal nekte å starte hvis `VISITOR_KEY` er kortere enn 24 tegn eller `ADMIN_PASSWORD` er kortere enn 16 tegn.

## 8. Frontend (besøkende)

Språk: norsk bokmål. Mobil først (de fleste åpner lenken fra en melding), fungerer fra 360 px bredde.

**Innhold, ovenfra og ned:**
1. Overskrift «Kom på besøk i Tromsø» og liten tekst «Oppdatert for X min siden».
3. Månedsvisning med forrige/neste-knapper, begrenset til horisonten. Uka starter på mandag. Vis **ukenummer** (ISO-8601) i egen kolonne til venstre. Ukedager: man tir ons tor fre lør søn.
4. Hver dagcelle representerer natta som starter den dagen. Ledig = grønn bakgrunn. Ikke ledig = nedtonet med gjennomstreking. Passerte datoer = nedtonet.
5. Forklaring under kalenderen: ledig natt / ikke ledig / «Tallet = natta som starter den dagen».
6. Periodevalg: første klikk = ankomstdag, andre klikk = avreisedag. Valgte netter markeres. Oppsummering: «3 netter ledig: fre 12. des til man 15. des». Er noen netter i perioden ikke ledige: «Ikke alle nettene i perioden er ledige. Prøv andre datoer.»
7. Knapp «Send forespørsel på e-post» når perioden er ledig. Åpner `mailto:` til `CONTACT_EMAIL` med emne «Besøk i Tromsø DD.MM–DD.MM» og ferdig utfylt brødtekst med datoer, og antall netter. Ingen e-postsending fra server.

**Stil:** rolig og skandinavisk. Hvit/lys bakgrunn, én aksentfarge, systemfont, ingen skygger eller gradienter. Støtt mørk modus via `prefers-color-scheme`. Tilgjengelighet: celler er `<button>` med `aria-label` («Natt til lørdag 13. desember, ledig»), tastaturnavigasjon med piltaster, synlig fokus, kontrast WCAG AA. Ikke stol på farge alene (gjennomstreking for ikke ledig).

Datoformat: `fre 12. des`, `12.12.2026`. Bruk `Intl.DateTimeFormat('nb-NO')`.

## 9. Admin-side

Enkel tabell over valgt måned: dato, hjemme, gjesterom ledig, og årsaker (kilde, hendelsestittel, hvilken regel i 4.2 som slo til). Knapp «Hent på nytt». Status per kilde: siste vellykkede henting og eventuell feil (uten URL).

## 10. Konfigurasjon (`.env.example`)

```
ICS_SHARED=
VISITOR_KEY=        # minst 24 tegn, generer med: python -c "import secrets;print(secrets.token_urlsafe(24))"
ADMIN_USER=
ADMIN_PASSWORD=     # minst 16 tegn
CONTACT_EMAIL=
TZ_LOCAL=Europe/Oslo
NIGHT_START=18:00
NIGHT_END=09:00
HORIZON_DAYS=365
REFRESH_MINUTES=15
```

## 11. Tester (må finnes og passere)

Lag egne ICS-fixtures. `availability.py` testes uten nettverk. Minst:

1. Heldagshendelse fredag blokkerer torsdag natt og fredag natt, ikke onsdag eller lørdag natt.
2. Flerdagers heldagshendelse (fre–søn, DTEND eksklusiv) blokkerer riktige netter.
3. Tidsbestemt hendelse 19:00–22:00 blokkerer ikke.
4. Tidsbestemt hendelse 22:00–07:00 (nattevakt) blokkerer.
5. `#hjemme` i tittel på heldagshendelse → ingen blokkering.
6. `#borte` på hendelse 08:00–09:00 → blokkerer natta før.
7. Ukentlig gjentakende heldagshendelse med én EXDATE og én flyttet forekomst (RECURRENCE-ID).
8. Vanlig hendelse i `ICS_SHARED` setter `home=false`.
9. `Gjest: Mamma` i `ICS_SHARED` setter `room=false`, men `home` forblir `true`.
10. Overgang til vintertid (siste søndag i oktober) og sommertid (siste søndag i mars): nattvinduene beregnes korrekt i lokal tid.
11. Hendelse med UTC-tid og hendelse med TZID=Europe/Oslo gir samme resultat.
12. Kilde som feiler beholder forrige resultat; `/healthz` viser siste vellykkede henting.
13. `/api/nights` uten eller med feil nøkkel → 404. Svar inneholder aldri feltet `title` eller tekst fra fixtures.
14. Ledighets- og periodeberegningen i frontend (ekstraher til en ren JS-funksjon og test med en enkel Node-test, uten avhengigheter).

## 12. Akseptansekriterier

- `docker build` og `docker run --env-file .env` gir fungerende app på port 8000.
- `pytest` passerer.
- Med tre gyldige iCal-URL-er vises korrekt tilgjengelighet innen 30 sekunder etter oppstart.
- Besøkende kan på mobil bla måneder, velge en periode og åpne en ferdig utfylt e-post.
- Ingen hendelsesdata eller hemmeligheter kan nås uten admin-innlogging.
- `README.md` forklarer på norsk: hvordan hver av oss finner hemmelig iCal-adresse (også for felleskalenderen), hvordan generere nøkler, og hvordan deploye i Coolify med persistent volum for `data/`.

## 13. Infrastruktur og deploy (Coolify på Hetzner)

Appen deployes på Coolify, enten basbeta.no-instansen eller en privat instans. Koden skal virke likt på begge; ingen basbeta-spesifikke avhengigheter.

- **Repo:** privat GitHub-repo. Hemmeligheter ligger kun i Coolifys «Environment Variables», aldri i repoet.
- **`.gitignore`** skal minst inneholde: `.env`, `.env.*`, `!.env.example`, `data/`, `__pycache__/`, `*.pyc`, `.venv/`, `venv/`, `.pytest_cache/`, `.DS_Store`, `*.log`, `node_modules/`.
- **Coolify-oppsett** (dokumenteres i README, steg for steg):
  - Build Pack: **Dockerfile** (ikke Nixpacks, Coolify bytter ikke automatisk).
  - Port: **8000** (Coolify foreslår 3000, og maler med nginx bruker 80; begge er feil her).
  - Persistent Storage: volum montert på **`/app/data`**, ellers forsvinner cachen ved hver deploy.
  - Healthcheck: `GET /healthz`.
  - Domene med https, f.eks. `besok.<ditt-domene>`; Traefik i Coolify ordner SSL.
- **Rekkefølge anbefalt i README:** deploy først med bare `VISITOR_KEY`, `ADMIN_USER`, `ADMIN_PASSWORD` satt og tomme ICS-variabler. Appen skal da starte, vise en tom kalender og `/healthz` skal svare. Legg deretter inn ICS-URL-ene. Slik er pipeline og app verifisert hver for seg.
- **Tomme ICS-variabler** er lov: appen starter, og alle netter regnes som ledige for personen uten kilde. `/healthz` og admin-siden viser at kilden mangler.
- **Data og personvern:** kalenderdata hentes fra Google (ICS) og behandles kun i minnet og i `data/cache.json` på serveren. Ingen tredjepartstjenester for analyse, feilsporing, fonter eller CDN.
- **Bak proxy:** appen kjører bak Traefik. Bruk første verdi i `X-Forwarded-For` som klient-IP for rate limiting, med fallback til socket-adressen.

## 14. Utenfor scope i v1

OAuth/Google API, booking som skriver tilbake til kalenderen, varsler, flere gjesterom, flerspråklighet, brukerkontoer for besøkende.
