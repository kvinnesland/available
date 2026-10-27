# Kom på besøk – besøkskalender for Tromsø

Viser venner og familie hvilke netter det passer å komme på besøk. Appen leser felleskalenderen fra Google Kalender (hemmelig iCal-adresse) og viser bare «ledig / ikke ledig» per natt. Ingen titler eller detaljer fra kalenderne når frem til besøkende.

Full bestilling: [`SPEC.md`](SPEC.md). Valg tatt underveis: [`DECISIONS.md`](DECISIONS.md).

## Slik tolkes kalenderne

En natt er natta som **starter** den datoen (natt 12. des = 12. til 13. des).

En hendelse gjør at du regnes som borte en natt når:

| Hendelse | Blokkerer natta hvis … |
|---|---|
| Heldag (også flere dager) | den berører kvelden (fra 18:00) eller morgenen (til 09:00). En heldag fredag blokkerer derfor torsdag og fredag natt. |
| Med klokkeslett | den går over kjernenatta 00:00–06:00 (nattevakt, sen flyreise). Middag 19–22 blokkerer ikke. |
| Tittel med `#borte` | den berører kveld, natt eller morgen, uansett klokkeslett. |
| Tittel med `#hjemme` | aldri. Bruk for heldags-påminnelser som ikke betyr fravær. |
| Avlyst | aldri. |

Alle hendelser i felleskalenderen følger tabellen over. Hendelser som starter med `Gjest:` eller `Besøk:` betyr at gjesterommet er opptatt:
- Heldag: legg inn fra ankomstdag til avreisedag. «Gjest: Mamma» fre–søn gir opptatt fredag og lørdag natt. Én dag gir én natt.
- Med klokkeslett: opptatt de nettene oppholdet går over 00:00–06:00.

## Finne den hemmelige iCal-adressen

Gjøres av den som eier felleskalenderen, på en datamaskin (ikke i mobilappen). Google endrer navn på menyvalg av og til, så teksten kan avvike litt:

1. Åpne [calendar.google.com](https://calendar.google.com), tannhjulet → **Innstillinger**.
2. Velg kalenderen i venstremenyen under «Innstillinger for kalenderne mine».
3. Under **Integrer kalender**, kopier **Hemmelig adresse i iCal-format** (slutter på `basic.ics`).

Ser du ikke feltet, mangler du rettigheten «Gjøre endringer og administrere deling», eller så har administratoren slått det av (gjelder Google Workspace-kontoer).

Adressen gir lesetilgang til hele kalenderen. Behandle den som et passord. Har den lekket: trykk **Tilbakestill** samme sted og oppdater miljøvariabelen.

## Generere nøkler

```bash
python3 -c "import secrets;print(secrets.token_urlsafe(24))"   # VISITOR_KEY
python3 -c "import secrets;print(secrets.token_urlsafe(18))"   # ADMIN_PASSWORD
```

Lenken du sender til familien er `https://<domene>/?k=<VISITOR_KEY>`. Bytter du nøkkelen, slutter gamle lenker å virke.

Admin-siden er `https://<domene>/admin` (brukernavn og passord fra `ADMIN_USER` / `ADMIN_PASSWORD`). Den viser hvorfor hver natt er blokkert.

## Deploy i Coolify

1. **+ Add Resource** → **Private Repository (with GitHub App)** → velg dette repoet, branch `main`.
2. **Build Pack: Dockerfile.** Coolify foreslår Nixpacks og bytter ikke selv.
3. **Port: 8000.** Coolify foreslår 3000, og basbeta-malen bruker 80. Begge er feil her.
4. **Persistent Storage** → legg til et volum (Volume Mount) med destinasjon **`/app/data`**. Uten dette forsvinner cachen ved hver deploy. Bruk volum, ikke bind mount, ellers eies mappen av root og appen får ikke skrevet.
5. **Domains**: f.eks. `https://besok.<ditt-domene>`, lagre.
6. **Environment Variables**: sett først bare `VISITOR_KEY`, `ADMIN_USER`, `ADMIN_PASSWORD` og `CONTACT_EMAIL`. La ICS_SHARED stå tom.
7. **Deploy.** Sjekk at `https://<domene>/healthz` svarer og at `/?k=<nøkkel>` viser en helt grønn kalender. Da virker pipeline, domene og SSL.
8. Legg inn `ICS_SHARED`, og deploy på nytt (eller bare restart). Sjekk `/admin` at alle kildene har «Sist hentet» og ingen feil.

Healthcheck er innebygd i Dockerfile (`GET /healthz`). Appen nekter å starte hvis `VISITOR_KEY` er under 24 tegn eller `ADMIN_PASSWORD` under 16.

## Kjøre lokalt

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # fyll ut
set -a; . ./.env; set +a
uvicorn app.main:build --factory --port 8000 --no-access-log
```

Eller med Docker:

```bash
docker build -t besok . && docker run --rm -p 8000:8000 --env-file .env -v besok-data:/app/data besok
```

## Tester

```bash
pytest                              # tilgjengelighetslogikk, API, sikkerhet
node --test tests/modes.test.js     # ledighet og perioder i frontend
```

## Oppdatere avhengigheter

Kun pakkene i `requirements.in` er tillatt (se SPEC.md). Lås med hasher, i Python 3.12:

```bash
pip install pip-tools
pip-compile --generate-hashes --strip-extras --allow-unsafe -o requirements.txt requirements.in
pip-compile --generate-hashes --strip-extras --allow-unsafe -o requirements-dev.txt requirements-dev.in
```

## Personvern

Kalenderdata hentes fra Google og ligger bare i minnet og i `data/cache.json` på serveren. Besøkende får bare `{date, h, m, room}` per natt. Ingen analyse, feilsporing, fonter eller CDN fra tredjeparter. Tilgangsloggen er slått av fordi den ville lagret besøksnøkkelen.
