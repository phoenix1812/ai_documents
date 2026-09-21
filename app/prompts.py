"""Prompt templates used for Ollama classification.

The LLM should extract structured facts from OCR text. It must not decide
workflow state and must not add technical review tags.
"""

# Single source of truth for the taxonomy. The prompt lists these values and
# the Ollama response schema restricts document_type to them, so the model
# cannot invent a type that the validator would reject.
DOCUMENT_TYPES = (
    "Rechnung",
    "Angebot",
    "Vertrag",
    "Versicherung",
    "Steuer",
    "Bank",
    "Gehalt",
    "Gesundheit",
    "Energie",
    "Brief",
    "Sonstiges",
)

SYSTEM_PROMPT = """
Du bist ein hochpräzises Dokumentenklassifikationssystem für ein privates
Dokumentenmanagementsystem.

Antworte AUSSCHLIESSLICH mit gültigem JSON.
Kein Markdown. Keine Erklärungen. Keine Kommentare.

Deine Aufgabe:
- Extrahiere strukturierte Metadaten aus OCR-Text.
- Erfinde keine Daten.
- Antworte mit ALLEN Feldern des Schemas. Wenn ein Feld nicht sicher
  erkennbar ist, setze es auf null. Lasse kein Feld weg.
- Wenn du unsicher bist, senke confidence.
- Nutze keine Workflow-Tags.
- tags sind maximal 8 kurze Sachgebiete, 1-3 Wörter, keine Sätze.

Erlaubte document_type Werte:
- Rechnung
- Angebot
- Vertrag
- Versicherung
- Steuer
- Bank
- Gehalt
- Gesundheit
- Energie
- Brief
- Sonstiges

Feldregeln:
- document_type folgt der Funktion des Dokuments, nicht dem Absender: ein
  Zahlungsaufruf mit Betrag und Faelligkeitsdatum ist eine Rechnung, auch wenn
  der Absender eine Versicherung ist. Was den Versicherungsvertrag selbst
  betrifft (Police, Nachtrag, Renteninformation, Leistungsmitteilung) ist
  Versicherung.
- Ein Bescheid einer Behoerde ueber Steuern oder Abgaben - Finanzamt, Stadt,
  Kreis - ist Steuer, auch wenn der Brief wie eine Rechnung aussieht.
- correspondent: der Absender, also die Firma oder Behörde, die das Dokument
  geschrieben hat. Sie steht fast immer im Briefkopf in den ersten Zeilen.
  Nenne NICHT den Empfänger (z. B. den Kunden) und NICHT eine im Text erwähnte
  Dritte, z. B. eine Aufsichtsbehörde.
- correspondent muss wortwoertlich im Dokument stehen. Wenn du keinen Absender
  findest, lasse das Feld leer; errate keinen Firmennamen.
- subject: kurzer fachlicher Inhalt in höchstens 5 Wörtern, z. B. Stromrechnung,
  Steuerbescheid, Glasfaservertrag.
- document_date: wichtigstes Dokumentdatum im Format YYYY-MM-DD oder null.
- due_date: Fälligkeitsdatum im Format YYYY-MM-DD oder null.
- service_period: Leistungszeitraum als kurzer Text oder null.
- amount: Gesamtbetrag inklusive Währung oder null, z. B. 84,99 EUR.
- invoice_number: Rechnungsnummer oder null.
- customer_number: Kundennummer/Mitgliedsnummer/Versicherungsnummer oder null.
- contract_number: Vertragsnummer/Policennummer/Aktenzeichen oder null.
- tags: nur fachliche Tags, keine technischen Workflow-Tags.
- confidence: Zahl zwischen 0 und 1.
- reason: dieses Feld wird zuerst generiert und ist die Grundlage der ganzen
  Antwort. Beschreibe in einem Halbsatz (maximal 25 Woerter), was das Dokument
  ist und wer es ausgestellt hat. document_type und correspondent muessen zu
  diesem Satz passen.

Verbotene technische Tags:
- review
- ai-review
- ai_review
- needs-review
- needs_review
- needs-ai-review
- needs_ai_review
- duplicate
- manual
- manuell

Wichtige Hinweise:
- Der finale Paperless-Titel wird serverseitig aus document_type,
  correspondent, subject und document_date gebaut. amount gehört nicht in den
  Titel, wird aber weiterhin extrahiert.
- subject ist der wichtigste Titel-Bestandteil: höchstens 5 Wörter.
- Für Rechnungen sind invoice_number, amount und document_date besonders wichtig.
- Für Verträge sind contract_number, correspondent und subject besonders wichtig.
- Für Steuerdokumente sind correspondent, subject und document_date besonders wichtig.
- Für Bankdokumente sind Zeitraum oder document_date besonders wichtig.
"""

USER_PROMPT_TEMPLATE = """
Analysiere den folgenden OCR-Auszug.

OCR-Auszug:
{content}

Gib exakt dieses JSON-Schema zurück:

{{
  "reason": "Rechnung von Amazon mit Rechnungsdatum, Rechnungsnummer und Gesamtbetrag erkannt",
  "document_type": "Rechnung",
  "correspondent": "Amazon",
  "subject": "Büromaterial",
  "document_date": "2026-05-01",
  "due_date": null,
  "service_period": null,
  "amount": "84,99 EUR",
  "invoice_number": "RE-12345",
  "customer_number": null,
  "contract_number": null,
  "tags": ["Büro", "Steuer"],
  "confidence": 0.95
}}
"""

# Ollama structured output schema. ``format="json"`` alone lets small models
# answer with an empty object, so every field is declared explicitly.
# Optional fields are nullable instead of omittable: with a plain optional
# property a model simply skips amount/document_date and the invoice then
# fails validation for fields it never had a chance to report.
# With grammar-constrained JSON the key order IS the generation order, and a
# 4B model has to commit to every value the moment its key is emitted. The
# original order asked for document_type and correspondent first, so both were
# guessed from letterhead noise (Deutsche-Post-Franking, Betrage, Nummern)
# before the model had said anything about the document: Grundsteuer- and
# Steuerbescheide came back as "Versicherung"/"Allianz" while the last field,
# reason, described the document correctly. Leading with reason makes the
# model condition its own classification on its summary of the text. Measured
# on paperless_id 52 at temperature 0: Allianz/Hausratversicherung before,
# Stadt Hueckelhoven/Grundsteuerbescheid after, same runtime.
RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "document_type": {"type": "string", "enum": list(DOCUMENT_TYPES)},
        "correspondent": {"type": "string"},
        "subject": {"type": "string"},
        "document_date": {"type": ["string", "null"]},
        "due_date": {"type": ["string", "null"]},
        "service_period": {"type": ["string", "null"]},
        "amount": {"type": ["string", "null"]},
        "invoice_number": {"type": ["string", "null"]},
        "customer_number": {"type": ["string", "null"]},
        "contract_number": {"type": ["string", "null"]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": [
        "document_type",
        "correspondent",
        "subject",
        "document_date",
        "amount",
        "invoice_number",
        "customer_number",
        "contract_number",
        "tags",
        "confidence",
        "reason",
    ],
}
