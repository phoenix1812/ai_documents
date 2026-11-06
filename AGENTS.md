# AGENTS.md

Arbeitsregeln für diesen Repo. Inhaltlich steht fast alles im `README.md` –
diese Datei ergänzt nur, was dort nicht steht und wiederholt wird: wie gearbeitet
werden soll und welche Betriebsregeln am laufenden System hängen.

## Sprache und Belege

- Antworten auf Deutsch. Code-Kommentare, Docstrings und Bezeichner sind
  Englisch, UI-Texte und Doku Deutsch – beides im Bestand gemischt lassen.
- Behauptungen über den Betrieb sind Messungen, keine Erinnerungen: `file:line`
  gegen den laufenden Code, Zahlen aus einem nachvollziehbaren Lauf.
- Vor einem Urteil über seine Definition zuerst seine Begriffe verwenden; eine
  abweichende Lesart beziffern, nicht stillschweigend ersetzen.
- Frage in der Nachricht zuerst beantworten, auch wenn gerade ein eigener Strang
  läuft.
- "ich überlege", "kann man", "wie bewertest du" heißt Analyse ohne Umsetzung.
  Ein Imperativ ("bau", "ändere", "mess", "räum auf") ist die Freigabe – und nur
  für die genannte Breite.
- Freigaben in normalen Worten anbieten, nicht als geprägte Triggerwörter.

## Projekt

Paperless-ngx mit einem eigenen Klassifikations-Worker und einer Review-UI.
Paperless ist die einzige Wahrheit für Dokumente und Metadaten; SQLite
(`data/documents.db`) hält nur Workflow-Status, Review-Queue und Lernprotokoll.
Architektur, Services und Konfiguration: `README.md:41` und `README.md:668`.

## Befehle

```bash
.venv/bin/python -m pytest -q          # Tests laufen auf dem Host, nicht im Container
.venv/bin/python -m compileall -q app tests
bash scripts/check-env.sh
```

Der Image-Pin ist Python 3.12 (`README.md:777`); ein newer Python schlägt beim
Nachziehen der Pins fehl.

Messläufe gegen das laufende System laufen über eine Kopie in den Container, ohne
`/app` anzufassen:

```bash
docker cp app/roles.py ai-worker:/tmp/app_roles.py
docker exec -w /app -e PYTHONPATH=/app:/tmp ai-worker python /tmp/mein_skript.py
```

## Betrieb – seine Aktionen

Nicht ohne ausdrückliche Freigabe: `docker restart`/`compose down`/Neubau der
Images, Reboots, (Re-)Mounts, `docker pull` oder Entfernen von Bildern, Port-Scans
und Zugriffe auf Geräteparameter – Geräte nennt er selbst.

- Erst mounten, dann Docker starten. Ein Remount unter laufendem Docker zerstört
  die Containersicht auf die Medien.
- NAS ist 23:00–08:00 offline: alle Läufe, die eine Freigabe brauchen, in das
  Fenster 08:00–23:00, immer mit Timeout.
- `legacy-scans/` ist von zwei Alt-Scans die einzige Kopie. `paperless-media/` ist
  die Primärkopie der Medien. Beides nicht löschen oder verschieben.
- Prozesse nie per Muster töten: erst die PID belegen. Fremde Skripte können im
  Aufräum-Pfad landen und dort rebooten.
- Für Reruns nicht an `documents.db` biegen – force-Flag am Trigger-Endpunkt
  (`app/reprocess.py`), ein erzwungener Lauf überschreibt Paperless bewusst.
- `GO_LIVE.md` und `P0_README.md` sind bewusst weg; nicht wiederherstellen.
- Löschen nur nach vorher aufgezählter Kandidatenliste und Freigabe je Gruppe.
  Behalten oder Verschieben ist ein gültiger Vorschlag.
- Der Browser gehört ihm, sobald er übernommen hat: nicht neu laden, nicht
  navigieren, für Nachweise eine eigene Instanz.

## Secrets

- `.env`, `PAPERLESS_TOKEN` und die DB-Passwörter gehen nie in einen Commit;
  `.gitignore` deckt `.env` ab, die Kontrolle bleibt trotzdem vor jedem `push`.
- Aus Tool-Kommandos keine Geheimwerte: keine Env-Dumps, keine `cat` auf
  `standort.json`, `tarife.tab` oder `.env`. Benötigten Wert per Einzelfeld
  lesen odermtime entscheiden lassen.
- Gemeldet werden Secret-**Namen**, nie Werte – auch nicht teilweise.
- Ein Backup-Archiv unter `backups/` enthält `env.backup` und gilt damit als
  Secret: nicht auspacken, nicht nach außen kopieren, nicht in Antworten zitieren.

## Code-Regeln dieses Repos

- Geschlossene Kataloge statt Modell-Raten: `app/roles.py`, `app/deadline.py` und
  `app/classifier.py` lesen eng und verweigern bei Mehrdeutigkeit. Ein Feld leer
  lassen ist der korrekte Ausgang, wenn der Text nichts eindeutig hergibt – ein
  geratenes Datum oder eine gerollte Zahl ist ein Fehler, keine Teilleistung.
- Neue Extraktoren bleiben netzwerkfreie Module (Muster `app/deadline.py`):
  reine Funktionen, Konstanten oben, Begründung im Docstring, Tests gegen
  synthetische Proben.
- Tests enthalten **keine** echten Beträge, Namen oder Dokumenttexte aus dem
  Bestand – der enthält Geburtsurkunden und Steuer-IdNr. Synthese in derselben
  Form, Zeilenumbrüche und Umlautbehandlungen inklusive.
- Keine neue Spalte, keine neue Tabelle, kein Schema-Wechsel und kein neuer
  Dienst ohne sein Wort. Vorhandene Muster: `Database._add_column_if_missing`
  (`app/db.py:161`), Migrationen sind idempotent über `IF NOT EXISTS`.
- Nur das genannte Element ändern. Ein Diff, der validierte Nachbarn mit entfernt
  (Nav-Einträge, Tabellenspalten, Konfigurationszeilen), ist ein Fehler.
- Keine Rückwärtskompatibilitäts-Attrappen, keine Features für hypothetische
  Zukunft, keine Kommentare, die beschreiben was der Code tut.
- Keine Zeichen außerhalb des lateinischen Alphabets in Dateien oder Antworten
  (auch keine CJK-Kommentare, auch keine Emojis).

## Messbare Fallen

- macOS legt Namen als NFD an, Paperless und OCR schreiben NFC. Pfadprüfungen
  immer gegen den direkten Pfad, nie über `basename`-Vergleich – sonst entsteht
  ein falsches "fehlt".
- `ocr_excerpt` in der DB ist gekürzt; die Zeilenstruktur des Volltextes existiert
  nur in Paperless. Zeilenbasierte Auswertung braucht den API-Volltext.
- Die Paperless-Wortsuche trifft ganze Wörter: `Einspeisevergütung` liefert 0,
  `Einspeis` liefert Treffer. Komposita sind der Blinder Fleck.
- `created__gte`/`created__lte` filtern das **Eingangsdatum**, nicht den
  Abrechnungszeitraum; `after`/`before` greifen in 3.3.1 nicht.
- OCR zerlegt Tabellenköpfe ("Insgesamt - found sind zu zahlen -") und Zeilen;
  Spaltenzuordnung ist danach nicht mehr herstellbar.
- Konfiguration wird live gemessen, nicht aus dieser Datei abgelesen:
  `PROPOSAL_SOURCE`, `DRY_RUN`, `CONFIDENCE_THRESHOLD` und
  `TYPE_EVIDENCE_REQUIRED` bestimmen, ob überhaupt etwas automatisch geschrieben
  wird.
