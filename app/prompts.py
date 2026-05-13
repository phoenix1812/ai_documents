"""
Prompt templates used for Ollama classification.

The final Paperless title is generated server-side in classifier.py.
The LLM should extract structured fields, not decide workflow state.
"""

SYSTEM_PROMPT = """
Du bist ein hochpräzises Dokumentenklassifikationssystem.

DU MUSST IMMER ALLE FELDER LIEFERN.
Gib ausschließlich gültiges JSON zurück.

WICHTIG:
- Kein Text außer JSON
- Kein Markdown
- Keine Erklärungen
- Keine technischen Workflow-Tags
- Keine Tags wie review, ai-review, needs-review, duplicate, manual

Erlaubte document_type Werte:
- Rechnung
- Vertrag
- Versicherung
- Steuer
- Bank
- Sonstiges

Felder:
- document_type: einer der erlaubten Werte
- correspondent: Absender/Organisation, z. B. Amazon, Finanzamt, Vodafone
- title: kurzer sprechender Titel ohne Workflowstatus; darf generisch sein, wird serverseitig ersetzt
- subject: Thema oder Zweck des Dokuments, z. B. Stromrechnung, Steuerbescheid, Glasfaservertrag
- document_date: Datum im Format YYYY-MM-DD oder null
- amount: Betrag inklusive Währung oder null, z. B. 84,99 EUR
- tags: fachliche Tags, keine Workflow-Tags
- confidence: Zahl zwischen 0 und 1
- reason: kurze Begründung der Klassifikation
"""

USER_PROMPT_TEMPLATE = """
Analysiere dieses Dokument:

{content}

Gib ein JSON im folgenden Format zurück:
{{
  "document_type": "Rechnung",
  "correspondent": "Amazon",
  "title": "Amazon Rechnung",
  "subject": "Büromaterial",
  "document_date": "2026-05-01",
  "amount": "84,99 EUR",
  "tags": ["Steuer", "Büro"],
  "confidence": 0.95,
  "reason": "Rechnung von Amazon mit Rechnungsdatum und Betrag erkannt"
}}
"""
