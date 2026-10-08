# GST Tax Research Assistant — Functional Specification (FSD)

Draft v0.2 · 8 Oct 2026

## 1. Document control and purpose

This FSD defines what the GST Tax Research Assistant must do so it can be frozen and built. It covers functional behaviour, data scope, research listing and non-functional needs; technical architecture follows in a separate TSD.

| Item | Value |
| --- | --- |
| Version | 0.2 (draft for review) |
| Stage | Plan, awaiting freeze |
| Audience | Product owner, domain experts (CA / GST advocate), engineering, QA |
| Jurisdiction | India, Goods and Services Tax (central, integrated, state, UT, compensation cess) |
| Requirement IDs | FR-\<area\>-\<nn\> for functional, NFR-\<nn\> for non-functional |
| Priority key | MVP = first release; P2 = second; P3 = later |
| Delivery | MVP is built first as a POC (Docker, Postgres full-text search, public documents only), then hosted on AWS India region. |

Once frozen, any change to a requirement needs a version bump and sign-off from the product owner.

### Change log

| Version | Date | Summary |
| --- | --- | --- |
| v0.1 | 7 Oct 2026 | Initial draft |
| v0.2 | 8 Oct 2026 | Re-scoped Release 1 to a non-LLM research repository: keyword + citation + graph search; LLM, semantic search, planning and litigation moved to P2; added extraction-quality and completeness requirements; POC-first delivery |

## 2. Product overview

The product gives GST professionals one place to find every relevant section, rule, notification, circular and judgement, with exact citations and links to amendments.

**Problem.** GST law changes constantly. The Acts are amended through Finance Acts, the Rules through notifications, and rates and exemptions through rate notifications. CBIC circulars and a growing body of AAR, High Court, Supreme Court and GSTAT rulings sit on top. Professionals rebuild the position by hand from scattered PDFs and paid databases. That work is slow, misses amendments, and can rely on law that has since been rescinded.

**Vision.** Enter a section, rule, topic, citation or keyword, with an optional date, and get a complete, grouped list of the relevant sections, rules, notifications, circulars and judgements, each opening at the exact paragraph.

### Personas

| Persona | Primary jobs | What success looks like |
| --- | --- | --- |
| Practising CA / GST consultant | Advisory opinions, client queries, compliance positions | Finds every relevant provision, notification, circular and judgement in minutes |
| GST advocate / litigation counsel | SCN replies, appeals, writ petitions, precedent search | Finds every precedent on the issue with amendment links |
| In-house tax manager | Transaction review, ITC decisions, notice handling | Gets the applicable law and recent rulings on the provision in one place |
| Article assistant / junior associate | Research legwork, summaries, case notes | Locates all sources for the issue before drafting |
| Firm admin / knowledge manager | Users, matters, internal precedents | Firm research and notes saved and searchable |

### Value proposition

- **Point-in-time accuracy:** shows what the law said on the transaction date, not only today.
- **Completeness you can check:** coverage shown, results not capped, misses reportable.
- **Linked research:** amendments, notifications, circulars and judgements tied to each provision.
- **Saved research:** matters, notes, export.
- **Stays current:** updates feed.

Drafting, planning advice and AI answers are planned for later phases.

## 3. Scope

Release 1 covers Indian GST research and listing using keyword, citation and link-graph search only. No generative AI, semantic search or planning features in MVP. Those follow in later phases (section 16).

### In scope

- Central GST law: CGST Act and Rules; IGST Act (others P2)
- CBIC notifications in every series (Central Tax, Central Tax (Rate), Integrated Tax, Integrated Tax (Rate), UT Tax, Compensation Cess), including Removal of Difficulties Orders published with them
- Circulars, instructions and orders
- Supreme Court, High Court and GSTAT judgements and orders from 1 July 2017
- Research search, grouped results, reader, matters, saved items, updates feed, export

### Deferred (P2 or later)

- Forms (REG, GSTR, DRC etc.)
- AAR/AAAR rulings
- GST Council material
- Constitution articles
- UTGST and Compensation Cess Acts and Rules
- IGST Rules
- State GST content
- Firm-uploaded documents
- AI question answering
- Planning and litigation assistants
- Semantic search

### Out of scope (Release 1)

- Filing returns or any GSTN integration
- Pre-GST laws (excise, service tax, VAT), except where transition provisions or judgements cite them
- Customs, income tax and other direct taxes
- Languages other than English (Hindi and regional-language judgements may follow later)
- Giving final legal advice: outputs support a professional and do not replace one

### Assumptions

- Users are qualified professionals or work under one, and do their own legal analysis.
- The system lists and links material and does not give conclusions.
- Primary sources are publicly available and may be lawfully collected and stored. Judgements come from court sites or a licensed reporter feed.
- State GST Acts mirror the CGST Act closely enough to map section by section. State-specific notifications are handled as a separate corpus.

### Constraints and dependencies

- Government portals change layout without notice, so scrapers need monitoring and manual fallback.
- Some older notifications and orders are scanned PDFs that need OCR.
- Personal and client data must comply with India's DPDP Act, 2023.
- Release 1 loads documents from files the team downloads, plus a fetch-by-URL option run on request; automatic crawling of government and court sites needs a legal review of site terms first.

## 4. Content corpus and source hierarchy

Every document is tagged with its authority level, so results rank binding law above guidance and guidance above commentary. When sources conflict, the system shows the higher authority first and names the conflict.

| Rank | Source type | Examples | Binding effect | Update frequency | Release |
| --- | --- | --- | --- | --- | --- |
| 1 | Constitution | Art. 246A, 269A, 279A, 286, 366(12A) | Supreme | Rare | P2 |
| 2 | Acts | CGST, IGST (others P2); amendments through Finance Acts | Binding | Each Finance Act | MVP (CGST, IGST); P2 (UTGST, Compensation Cess) |
| 3 | Supreme Court judgements | Interpretation of GST provisions and vires challenges | Binding on all | Weekly | MVP |
| 4 | Rules | CGST Rules 2017 (others P2) | Binding unless ultra vires | Monthly | MVP (CGST); P2 (IGST, others) |
| 5 | Notifications | Rate, exemption, procedure, due-date and RCM notifications | Binding (delegated law) | Weekly | MVP |
| 6 | High Court judgements | Writs on ITC, refunds, SCN procedure | Binding in that state; persuasive elsewhere | Daily | MVP |
| 7 | GSTAT orders | Appeals under Section 112 | Binding on lower authorities | As issued | MVP |
| 8 | Circulars, instructions, orders | CBIC clarifications under Section 168 | Bind officers, not taxpayers or courts | Monthly | MVP |
| 9 | AAR / AAAR rulings | Advance rulings under Sections 97 to 101 | Bind only the applicant and its officer; persuasive otherwise | Weekly | P2 |
| 10 | Council material, FAQs, press releases | Meeting minutes, recommendations | Persuasive, show intent | After each meeting | P2 |
| 11 | Firm content | Internal opinions, precedents | Private, persuasive | As uploaded | P2 |

Forms (REG, GSTR, DRC etc.) are P2; their authority rank is decided when added.

### Rules for the corpus

- **FR-COR-01 (MVP):** Store every document with type, issuing authority, number, date of issue, date in force, and status (in force, amended, superseded, rescinded, struck down, stayed).
- **FR-COR-02 (MVP):** Keep every version of the CGST and IGST Acts and CGST Rules as dated text, so the law can be rebuilt as it stood on any date since 1 July 2017.
- **FR-COR-03 (MVP):** Record the jurisdiction of each judgement: court, bench, state.
- **FR-COR-04 (P2):** Add state GST Acts, state notifications and state circulars for the 10 highest-volume states first. The state list will be confirmed at freeze.
- **FR-COR-05 (P2):** Keep firm-uploaded content in a tenant-isolated store. It is never used to answer another firm's questions. Release 1 has no private uploads.
- **FR-COR-06 (MVP):** Show a coverage statement for each source: what is loaded, up to which date, and known gaps.

## 5. Ingestion pipeline

Every new source document should be searchable within 24 hours of loading, with its metadata and amendment links checked. Anything the pipeline cannot parse confidently goes to a human review queue and is not dropped silently.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-ING-01 | Load official documents from files placed in a watch folder or fetched from a URL on request, per source, with source health shown. Automatic daily crawling of CBIC, GST Council, e-Gazette, court and tribunal sites is P2 and needs a legal review of site terms. | MVP |
| FR-ING-02 | Accept manual loads (PDF, DOCX, HTML, scanned images) from admins into the shared corpus. Private uploads by firm users: P2. | MVP |
| FR-ING-03 | Extract text from digital PDFs and OCR scanned ones. Store page and paragraph positions so citations point to an exact location. No text on a page may be dropped silently (covered by FR-ING-14). | MVP |
| FR-ING-04 | Split the Acts and Rules into chapter, section, sub-section, clause, proviso and explanation. Split notifications into paragraphs and tables (rate schedules by HSN/SAC). Split judgements into header, facts, issues, arguments, findings and order. | MVP |
| FR-ING-05 | Extract metadata with rules: patterns for numbers, series, dates, sections referred to, HSN/SAC, court names, case numbers. Fields below a confidence threshold, or failing cross-checks, go to a reviewer. Captures: number, date, series, issuing body, subject, sections referred to, effective date, HSN/SAC codes. For judgements: parties, court, bench, judges, date, citation, and appeal or writ number. | MVP |
| FR-ING-06 | Detect duplicates across sources, such as the same judgement from a court site and a reporter. Keep one canonical record that lists every source URL. | MVP |
| FR-ING-07 | Detect amending language ("substituted", "inserted", "omitted", "rescinded", "in supersession of") using rule-based patterns, split the instructions, and propose the change with its effective date for a reviewer. No generative model is used. | MVP |
| FR-ING-08 | A reviewer approves each proposed amendment before the consolidated text changes. Every approval is logged with the reviewer, time and source. | MVP |
| FR-ING-09 | Rebuild consolidated, point-in-time text of the Acts, Rules and rate schedules from the approved amendments. | MVP |
| FR-ING-10 | Show an ingestion dashboard: documents found, parsed, awaiting review, failed, and source health. Alert when a source stops yielding documents. | MVP |
| FR-ING-11 | Re-run parsing for a document or a whole source after a parser change, with a diff report. | P2 |
| FR-ING-12 | Ingest from a licensed case-law feed through a vendor API if one is contracted. | P2 |
| FR-ING-13 | Ingest Hindi and regional-language judgements with translation. | P3 |
| FR-ING-14 | Page accounting: every page of every file ends with a recorded status (text layer, OCR, or failed); pages in must equal pages out. | MVP |
| FR-ING-15 | Extraction cross-check: text is extracted by two independent methods; pages where they differ beyond a set margin, or that show garbled text (broken font encoding), are re-read by OCR and flagged. | MVP |
| FR-ING-16 | Nothing deleted: boilerplate such as headers, footers and non-English text is kept as flagged blocks and stays searchable at low weight; if structure parsing fails, the raw page text is still indexed, the original page is one click away, and the document is flagged for review. | MVP |
| FR-ING-17 | Gap detection: check numbering of notifications (per series and year) and circulars for missing numbers and alert the reviewer. | MVP |
| FR-ING-18 | Extraction quality gate: word recall of at least 99.5% on an expert-checked fixture set of digital, scanned, two-column and table-heavy PDFs, re-run on every parser change. | MVP |

**Acceptance:** a notification loaded on day D is searchable within 24 hours of loading in the production profile. Its links to the amended rule are shown, and asking for the rule's text on a date before the notification's effective date returns the old text. Every page of the file has a recorded extraction status.

## 6. Knowledge model

The core asset is a linked graph of provisions and the instruments that change or interpret them, each link dated. Links are built by citation parser rules and reviewer approval, never by a generative model. This graph is used to find everything that bears on a provision at a given date.

### Entities

| Entity | Key attributes |
| --- | --- |
| Provision | Act/Rules, number, heading, text versions with valid-from and valid-to dates |
| Notification | Series, number/year, date, effective date, status, provisions affected, HSN/SAC rows |
| Circular / instruction / order | Number, date, subject, provisions clarified, status (in force, withdrawn, held contrary by a court) |
| Judgement / ruling | Court, bench, date, parties, citation, issues, holding, provisions interpreted, outcome |
| Council recommendation | Meeting number, date, item, resulting notifications |
| Concept / topic | Taxonomy node, such as ITC > blocked credits > motor vehicles |
| HSN / SAC | Code, description, rate history with dates and source notifications |

### Relationships

- **FR-KM-01 (MVP):** Link amending instruments to target provisions: amends, inserts, substitutes, omits, rescinds, supersedes. Each link has an effective date.
- **FR-KM-02 (MVP):** Link notifications to their parent power, such as a Section 9(1) rate notification or a Section 11 exemption.
- **FR-KM-03 (MVP):** Link circulars to the provisions they clarify, and to judgements that uphold, read down or set them aside.
- **FR-KM-04 (MVP):** Link judgements to the provisions they interpret and to the judgements they cite.
- **FR-KM-05 (P2):** Classify how one judgement treats another: followed, relied on, distinguished, doubted, overruled, reversed in appeal, or stayed. A reviewer sets the label (a model may propose it once AI is added).
- **FR-KM-06 (P2):** Track appeals for each judgement and flag when a ruling is under appeal or has been reversed: "good law" status.
- **FR-KM-07 (MVP):** Map each provision and judgement to the topic taxonomy, so users can browse by topic and get alerts on it. This is done by keyword rules and reviewer, no generative model.
- **FR-KM-08 (MVP):** Keep HSN/SAC rate history, so the system can answer "what was the rate on date X, and which notification set it".
- **FR-KM-09 (MVP):** Mention index: scan every document for citations of provisions in any common written form (for example s.16(2), Sec 16, section 16(2)) and store each match as a 'mentions' link to the provision, so a provision page can list every document that mentions it.

**Acceptance:** opening Section 16(4) of the CGST Act shows its text on any chosen date, its amendment history, the circulars on it, and the leading judgements interpreting it, with the reviewer-set good-law flag where one exists.

## 7. Research and search

Users get one search box for keywords and citations; results are grouped, filterable, dated; each result opens at the exact paragraph.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-RES-01 | Keyword search: exact phrases, Boolean operators and proximity across the whole corpus, with word-form matching (stemming). No semantic search in Release 1. | MVP |
| FR-RES-02 | Recognise citations: typing "s.16(2)(c) CGST", "Notf 11/2017-CT(R)", "Circular 183/15/2022" or a case name or citation opens that document directly. | MVP |
| FR-RES-03 | Filter by document type, authority, court, state, date range, status (in force or not), topic, and HSN/SAC. Outcome filter (for or against the assessee): P2. | MVP |
| FR-RES-04 | **As-on date:** every search accepts a date (default today). Results use the law in force on that date. | MVP |
| FR-RES-05 | Cited AI answers in plain language with a conclusion, analysis and numbered citations. Deferred. | P2 |
| FR-RES-06 | Refine and re-run a search keeping the as-on date and filters. | MVP |
| FR-RES-07 | Show conflicting views side by side (needs reviewer-set treatment labels). | P2 |
| FR-RES-08 | Document reader: highlighted search hits, a version selector for provisions, a "what changed" diff between dates, and a panel of linked documents (section 6). | MVP |
| FR-RES-09 | Judgement summary generated on demand; deferred. | P2 |
| FR-RES-10 | Compare two dates for a provision or rate ("Rule 36(4) in Oct 2019 vs Jan 2022"). | P2 |
| FR-RES-11 | Saved searches record the query, filters, as-on date and corpus version, so a result list can be reproduced and exported as a research note. | MVP |
| FR-RES-12 | Find similar: from a judgement or paragraph, find judgements on the same issue (needs semantic search). | P2 |
| FR-RES-13 | Grouped results: results are grouped by type (sections, rules, notifications, circulars, judgements by court level), ordered by authority, then relevance, then recency, with a count per group. | MVP |
| FR-RES-14 | Provision page 'everything linked': for any section, rule or notification, show complete, unranked lists of amending and issuing notifications, clarifying circulars, judgements that interpret or mention it, and the mention index (FR-KM-09). | MVP |
| FR-RES-15 | No result caps: show the total count; all results can be paged through; the full list can be exported (CSV, DOCX or PDF). | MVP |
| FR-RES-16 | Visible query expansion: synonyms, abbreviations and citation variants that were also searched are shown (for example 'also searched: ITC, input tax credit') and can be switched off. The synonym list is maintained by experts. | MVP |
| FR-RES-17 | Coverage statement: every results page shows, per source, what is loaded, up to which date, and known gaps (FR-COR-06). | MVP |
| FR-RES-18 | Report a miss: a button on any results page lets the user report a document that should have been found. It creates a review task; confirmed misses are added to the expert query set. | MVP |
| FR-RES-19 | Status shown inline: every result shows its status on the as-on date (in force, amended, superseded, rescinded, struck down, stayed; for circulars, withdrawn or held contrary; for judgements, the reviewer-set good-law flag where one exists). | MVP |

**Acceptance:** searching 'section 17(5)(a)' with an as-on date before 1 Feb 2019 returns the provision text as it stood then; the same search for a later date returns the amended text. The page lists the amending instruments, the clarifying circulars, and every judgement that mentions the provision, grouped by type with counts, with nothing cut off by a result cap. The coverage statement is visible.

## 8. Tax planning assistant

Deferred: this section is not part of Release 1. It depends on the AI features in section 11 and on the research core.

The planning assistant takes a described transaction and returns a structured GST analysis. That covers supply, classification, rate, place of supply, time and value of supply, ITC and compliance. Each conclusion is cited and given a risk rating, so the professional can see where the position is settled and where it is arguable.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-PLN-01 | Transaction intake: a guided form or free text that captures the parties and their GSTINs or states, the goods or services, the consideration, related-party status, dates, and the contract documents (upload). | P2 |
| FR-PLN-02 | Issue spotting: list the GST questions the transaction raises, such as supply or not, composite or mixed, intermediary, export, RCM, related-party valuation, or Schedule I/III. | P2 |
| FR-PLN-03 | Classification aid: suggest HSN/SAC candidates with reasons, using the tariff, the explanatory notes, rate notifications and AAR rulings on similar products. Show the rate history for each candidate. | P2 |
| FR-PLN-04 | Place of supply: work through the IGST Act sections that apply (Sections 10 to 13) and show the steps taken. | P2 |
| FR-PLN-05 | ITC eligibility: check Sections 16 and 17, the blocked credits, Rule 36, Rule 42/43 reversals, and time limits. Show conditions met, conditions not met, and gaps in the facts. | P2 |
| FR-PLN-06 | Valuation: Section 15 and Rules 27 to 35 for related or distinct persons, discounts and free supplies. | P2 |
| FR-PLN-07 | Scenario comparison: compare two or more structures (for example, a bundled vs separate contract) across tax cost, ITC flow, cash flow and litigation risk in one table. | P2 |
| FR-PLN-08 | Risk rating per conclusion: Settled, Favourable, Arguable or Adverse. Each rating gives its reason and cites the judgements both ways. | P2 |
| FR-PLN-09 | Opinion draft: produce a client opinion in the firm's template (facts, issues, law, analysis, conclusion, caveats), editable and exportable to Word. | P2 |
| FR-PLN-10 | Missing-facts prompts: when a conclusion turns on a fact the user has not given, ask for it instead of assuming it. | P2 |

**Acceptance:** for a sample software licence plus support contract, the assistant identifies the composite-supply question, cites Section 2(30) and Section 8, proposes SAC codes with rates, and flags the facts it still needs. An expert reviewer rates the draft as "usable with minor edits" in at least 70% of 50 test scenarios.

## 9. Litigation assistant

Deferred: this section is not part of Release 1. It depends on the AI features in section 11 and on the research core.

The litigation assistant reads a notice or order, finds its weak points, and drafts the reply or appeal with supporting precedents. Every draft is marked as a draft for professional review, and every precedent it relies on is checked against good-law status.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-LIT-01 | Upload an SCN, DRC-01/01A, assessment or adjudication order, or appellate order. Extract the notice number, date, section invoked (73 / 74 / 74A / 76 / 122 / 129 / 130), period, demand split into tax, interest and penalty, allegations, and the reply due date. | P2 |
| FR-LIT-02 | Procedural checks: limitation under the invoked section, a proper DIN, pre-SCN intimation where required, jurisdiction, monetary limits of the officer, reasons and details given, and a personal hearing offered. Flag each defect with the provision and supporting judgements. | P2 |
| FR-LIT-03 | Issue-wise analysis: for each allegation, give the legal position, the judgements for and against the taxpayer, and a suggested line of defence with a risk rating (as in FR-PLN-08). | P2 |
| FR-LIT-04 | Draft a reply to the SCN in the firm's template: preliminary objections, issue-wise submissions, case law, and prayer. Fully editable. | P2 |
| FR-LIT-05 | Draft appeals: grounds of appeal and statement of facts for appeals under Section 107 (Appellate Authority) and Section 112 (GSTAT), plus a writ outline for the High Court. | P3 |
| FR-LIT-06 | Limitation and pre-deposit calculator: work out due dates from the order date and communication date, with condonable periods (for example, Section 107: 3 months plus 1 month condonable) and the pre-deposit amount. All rules are held in configurable tables that cite their source. | P2 |
| FR-LIT-07 | Precedent finder: given a fact pattern, list the most relevant judgements ranked by authority (binding in the user's state first), how recent they are, and how similar the facts are, with good-law status. | P2 |
| FR-LIT-08 | Case-file workspace: a matter holds its notices, replies, orders, hearing dates, research notes and drafts, with a timeline of events. | P2 |
| FR-LIT-09 | Compilation: build a case-law compilation (index plus extracts) for filing or a hearing, exportable as PDF. | P3 |

**Acceptance:** for a sample Section 74 SCN alleging fake ITC, the assistant extracts the demand correctly. It flags a limitation defect where one has been planted, lists at least 5 relevant judgements with good-law status, and produces a reply draft that a GST advocate rates usable with edits.

## 10. Workspace, alerts and collaboration

Matters are the unit of work. Research, saved items and notes live inside a matter. From P2 the system also watches each matter for changes in law that affect it.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-WS-01 | Create matters with client, GSTINs, period, topics and team members. Every query, saved document, note and draft can be filed to a matter. | MVP |
| FR-WS-02 | Save items with annotations: bookmark a document or paragraph and add a private or team note. | MVP |
| FR-WS-03 | Daily updates feed of new notifications, circulars and important judgements, filtered by the user's topics, showing title, type, number, date and the sections referred to (no generated summary). | MVP |
| FR-WS-04 | Daily or weekly email digest of the updates feed, at the user's choice. Email delivery is part of the production profile; the POC shows the digest in the app. | MVP |
| FR-WS-05 | Matter impact alerts: when a new instrument or judgement touches a provision, topic or HSN/SAC linked to an open matter, alert the matter team and explain why it matters. | P2 |
| FR-WS-06 | Deadline tracker: reply dates, hearing dates and appeal limitation from FR-LIT-06, with reminders 7, 3 and 1 days before. | P2 |
| FR-WS-07 | Sharing within the firm by matter, with view or edit rights. Comments and @mentions on notes and drafts. | P2 |
| FR-WS-08 | Export search results, research notes and saved items to DOCX and PDF with the firm's letterhead and the full list of sources. | MVP |
| FR-WS-09 | Firm knowledge base: approved internal opinions become searchable for that firm only, tagged as internal. | P2 |

## 11. AI answer quality and guardrails (deferred to P2)

Not part of Release 1, which has no generative AI. These requirements apply when AI answers are added. No AI statement about the law may reach the user without a citation that the system has checked against the stored source. When the corpus does not support an answer, the assistant says so rather than filling the gap.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-AI-01 | Grounding: answers are generated only from passages retrieved from the corpus and the matter's documents. The model's general knowledge may frame the analysis but cannot be the sole support for a legal proposition. | P2 |
| FR-AI-02 | Citation check: before display, every citation is matched to a stored document and paragraph, and the quoted or paraphrased text is checked against it. A citation that fails is removed and the claim it supported is marked "unsupported". | P2 |
| FR-AI-03 | No invented authorities: a case name, notification or circular number that is not in the corpus is never shown as a citation. | P2 |
| FR-AI-04 | Temporal check: each cited provision or notification must have been in force on the as-on date. If not, the answer says so explicitly. | P2 |
| FR-AI-05 | Status check: cited circulars and judgements show their status (withdrawn, stayed, overruled, under appeal) inline. | P2 |
| FR-AI-06 | Confidence label per answer: High (settled, binding source), Medium (persuasive or split), Low (little or no authority). A Low answer suggests what to check next. | P2 |
| FR-AI-07 | Quote exactly: text in quotation marks must match the source word for word. | P2 |
| FR-AI-08 | Disclaimer on every results page and export: research aid, not legal advice; verify against official sources before reliance. | MVP |
| FR-AI-09 | Feedback: thumbs up or down plus a reason on each answer and citation. Flagged items go to an expert review queue. | P2 |
| FR-AI-10 | Privacy: client documents are not used to train models. The model provider must contractually agree to zero retention. | P2 |
| FR-AI-11 | Prompt safety: text inside uploaded documents is treated as data, never as instructions to the assistant. | P2 |
| FR-AI-12 | Model versioning: every answer stores the model, prompt version and retrieved passages, so it can be reproduced in an audit. | P2 |

## 12. User roles, permissions and admin

The product is multi-tenant: each firm is a tenant, and roles control access within it. A separate platform team, not firm users, curates the shared legal corpus.

| Role | Scope | Can do |
| --- | --- | --- |
| Platform content editor | All tenants (shared corpus) | Approve ingestion, amendments, metadata and judgement treatment; fix errors |
| Platform admin | All tenants | Manage tenants, plans and sources; view audit logs |
| Firm admin | Own firm | Manage users, seats, SSO, templates, letterhead and firm knowledge base; view firm usage |
| Partner / senior | Own firm | Everything a professional can, plus approving drafts and internal opinions for the knowledge base |
| Professional | Own firm, assigned matters | Research, plan, draft, create matters, share within the firm |
| Junior / article | Own firm, assigned matters | Research and draft. Exports carry a "not reviewed" watermark until a senior approves them. |
| Read-only / client viewer (P3) | Shared matter only | View exported, approved outputs |

In the POC, local logins and a reduced set of roles are used (platform content editor, platform admin, professional). The full firm role set applies in the production profile.

- **FR-ADM-01 (MVP):** Email and password login. MFA is added in the production profile. SSO (SAML / OIDC) in P2.
- **FR-ADM-02 (MVP):** Matter-level access control. A user sees only matters they are a member of, plus firm-wide items.
- **FR-ADM-03 (MVP):** Audit log of logins, document uploads, exports, sharing and admin changes, kept for 7 years.
- **FR-ADM-04 (P2):** Usage dashboard per firm: queries, active users, drafts and exports.
- **FR-ADM-05 (P2):** Subscription plans with seat counts and usage limits. Billing integration is in scope; payment collection uses a third-party gateway.

## 13. Non-functional requirements

Each requirement says whether it applies to the POC or only to the production profile. The targets below are proposed starting values to confirm at freeze. They assume up to 5,000 named users and a corpus of about 500,000 documents in the production profile.

| ID | Area | Requirement | Applies to |
| --- | --- | --- | --- |
| NFR-01 | Search speed | Keyword or citation search returns results in under 1.5 s at p95 | POC (indicative) and production |
| NFR-02 | Answer speed | Q&A starts streaming within 4 s and completes within 30 s at p95 | P2 (AI answers) |
| NFR-03 | Drafting speed | SCN reply or opinion draft is ready within 3 minutes | P2 (drafting) |
| NFR-04 | Freshness | New documents are searchable within 24 h of loading; consolidated text is updated within 48 h of approval | POC and production |
| NFR-05 | Availability | 99.5% monthly, excluding announced maintenance | Production |
| NFR-06 | Scale | 200 concurrent users at launch; the design must grow to 10x without a re-architecture | Production |
| NFR-07 | Data residency | All customer data and the corpus stored in India | Production |
| NFR-08 | Privacy | DPDP Act 2023 compliance: consent, purpose limitation, data-principal rights, breach notification | Production |
| NFR-09 | Security | TLS 1.2+ in transit, AES-256 at rest, tenant isolation, OWASP ASVS L2, annual third-party penetration test | Production |
| NFR-10 | Retention | Firm data kept for the life of the subscription plus 90 days, then deleted. Firms can export all their data. | Production |
| NFR-11 | Auditability | Every saved search can be reproduced from its stored inputs (FR-RES-11); AI answers join this in P2 | POC and production |
| NFR-12 | Accessibility | WCAG 2.1 AA for the web app | POC and production |
| NFR-13 | Platforms | Latest two versions of Chrome, Edge, Safari and Firefox; responsive down to tablet. A mobile app is out of scope for Release 1. | POC and production |
| NFR-14 | Backup / DR | Daily backups, RPO 24 h, RTO 8 h | Production |
| NFR-15 | Cost control | Per-tenant tracking of AI usage cost, with configurable limits (applies when AI is added) | P2 (AI usage cost) |
| NFR-16 | Extraction quality | Word recall of at least 99.5% on the expert-checked fixture set (FR-ING-18) | POC and production |
| NFR-17 | Search completeness | At least 95% of the expert's must-find items appear in the full result list (section 15) | POC and production |

## 14. Key user journeys

These journeys define done for each phase. Release 1 journeys are UJ-1 to UJ-4 and UJ-7. Each is tested end to end with the acceptance criteria shown.

| # | Journey | Persona | Phase | Acceptance criteria |
| --- | --- | --- | --- | --- |
| UJ-1 | Research a topic as on a date: search "reverse charge legal services" as on Aug 2018 | Consultant | MVP | Results are grouped by type with counts; the notification in force on that date is listed with its entry; clarifying circulars and judgements that mention it are listed; every result opens at the right paragraph; status shown inline; coverage statement visible; results exported to DOCX in under 3 clicks |
| UJ-2 | Trace a provision: open Rule 36(4) and see every version and amending notification | Junior | MVP | Version timeline is complete since insertion; diff between any two dates; linked circulars and judgements listed |
| UJ-3 | Find the HSN rate on a date: "rate for HSN 8703 on 15 Mar 2021, and source" | In-house | MVP | Correct rate and cess, with notification number and entry; rate history shown |
| UJ-4 | Daily update: new circular on a followed topic | Consultant | MVP | Appears in the feed and digest within 24 h of loading, with title, type, number, date and topic tags |
| UJ-5 | Plan a transaction: describe a cross-border service arrangement, compare two structures | Consultant | P2 (deferred) | Issue list, place-of-supply steps, ITC view, scenario table, risk ratings, opinion draft in the firm template |
| UJ-6 | Respond to an SCN: upload a Section 74 SCN, get defects, precedents and a reply draft | Advocate | P2 (deferred) | Demand extracted correctly; procedural defects flagged with provisions; at least 5 relevant precedents with status; editable reply draft; due date added to the tracker |
| UJ-7 | Report a miss: the user cannot find a document they know exists | Consultant | MVP | The user presses Report a miss; a review task is created with the query, filters and as-on date; a reviewer can confirm it and add it to the expert query set |

Each journey also has a negative test. A search for something the corpus does not cover returns an empty result with the coverage statement and the Report a miss button, and invents nothing.

## 15. Success metrics and evaluation

Release quality is measured against an expert query set of about 100 to 200 research queries, each with a must-find list of sources, plus an expert-checked fixture set of PDFs for extraction. Both are built with practising GST professionals before MVP development starts. No release ships if a release-gate metric is below target.

| Metric | How measured | MVP target | Gate? |
| --- | --- | --- | --- |
| Extraction word recall | fixture set of digital, scanned, two-column and table-heavy PDFs | >= 99.5% | Yes |
| Page accounting | share of pages with a recorded extraction status | 100% | Yes |
| Must-find recall | share of must-find sources present in the full result list for each query, reported per document type | >= 95% overall (judgements and circulars each reported separately) | Yes |
| Temporal correctness | dated lookups of provision text and rates match expert-checked values | >= 99% | Yes |
| Broken links | shown links that do not open an existing document or paragraph | 0 | Yes |
| Unexplained numbering gaps | missing notification or circular numbers in loaded series with no explanation | 0 | Yes |
| Metadata accuracy | sample audit of number, date, status and section links | >= 98% | No |
| Link accuracy | sample audit of amendment, circular and mention links | >= 98% | No |
| Ingestion freshness | documents searchable within 24 h of loading (production profile) | >= 95% | No |
| Adoption | weekly active users divided by paid seats, 90 days after launch | >= 60% | No |
| Time saved | user survey: research time vs previous method | >= 50% reduction reported | No |
| Satisfaction | share of users rating results useful | >= 80% | No |

The query set is versioned and re-run on every parser, index, synonym-list or ranking change. A held-out part is never used for tuning. AI metrics (citation validity, invented authorities, answer correctness) return with the AI release in P2.

## 16. Release phasing

The MVP proves the hardest part, trustworthy point-in-time research, before any drafting is built on top of it. MVP is built first as a POC (Docker, Postgres full-text search), then deployed in the production profile on AWS India region. Each later phase starts only when the previous phase passes its quality gate (section 15).

| Phase | Focus | Contents | Gate to next phase |
| --- | --- | --- | --- |
| MVP (Release 1) | Research core | Research core: CGST and IGST Acts, CGST Rules, notifications, circulars, SC / HC / GSTAT judgements; point-in-time law and HSN rates; keyword, citation and graph search; grouped results; mention index; coverage statement; updates feed; matters, saved searches and export | Release gates in section 15 met (extraction recall, must-find recall, temporal correctness) |
| P2 (Release 2) | AI, planning and litigation | AI answers with citation checks; semantic search; judgement summaries; transaction analysis; SCN analysis and reply; forms; AAR/AAAR; Council material; UTGST and Compensation Cess; IGST Rules; state GST; alerts; SSO; firm uploads and tenant isolation | AI metrics met and drafts rated usable in >= 70% of 50 expert scenarios |
| P3 (Release 3) | Depth and reach | Appeal and writ drafting; case-law compilations; regional-language rulings; client viewer access | — |

Feature IDs marked MVP, P2 and P3 in sections 4 to 12 map to these phases. Calendar dates and team size are set at freeze.

## 17. Risks, open questions and decisions for freeze

The FSD can be frozen once the open dependency below is resolved. The risks stay on the register through delivery.

### Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Relevant material is missed in search or never loaded | Incomplete research, wrong position | Coverage statement, gap detection (FR-ING-17), no result caps, mention index, synonym list, must-find recall gate, Report a miss |
| Missed or misapplied amendment gives the wrong point-in-time law | Wrong advice | Human approval of amendments (FR-ING-08); temporal tests in query set |
| Court and government sites change or block scraping | Stale corpus | Source-health alerts, manual upload fallback, licensed feed option |
| Copyright or licence limits on reported judgements | Legal exposure | Use court-issued copies; licence a reporter only if needed |
| Text lost or garbled in PDF extraction | Missing or wrong text in results | Page accounting, two-method cross-check, garble detection, raw page fallback, fixture gate (FR-ING-14 to 18) |
| Client confidential data leaked (applies when uploads and AI are added in P2) | Regulatory and reputational harm | Zero-retention contract, India region, tenant isolation, DPDP compliance |
| Review backlog delays amendments and metadata | Stale consolidated text | Prioritise Acts and Rules, then Supreme Court and High Courts; rule-based pre-checks |
| Users rely on outputs without review | Liability | Disclaimer, terms of use |
| Keyword-only search misses relevant text that uses different words | Missed results | Expert synonym list, mention index, graph links, recall gate; semantic search in P2 if the gate fails |

### Decisions needed

#### Decided

- [x] No generative AI in Release 1; search is keyword, citation and graph only
- [x] MVP is built first as a POC on Docker and Postgres full-text search, then moved to AWS India region
- [x] POC corpus as listed in section 3, loaded from files, no automatic crawling
- [x] Target customer for MVP: corporate tax teams (in-house). Matters, saved searches and export matter more than firm templates. SSO stays P2 for the POC; revisit it before production, because corporate IT teams often require it
- [x] Case-law source: court sites and downloaded files only; no licensed reporter feed in Release 1
- [x] Courts to load first: Supreme Court, GSTAT and the highest-volume High Courts; the High Court list is confirmed when loading starts
- [x] Firm-uploaded documents are never used to improve shared features (default confirmed: no)
- [x] Production hosting: AWS India region (ap-south-1), with DR in ap-south-2
- [x] Legal review of court and government site terms is a mandatory gate before any automatic crawling

#### Not needed before the POC (decide before production)

- [ ] States in scope for P2 (proposed: top 10 by GST collection)
- [ ] Pricing model
- [ ] Brand and product name (placeholder: taxresearch)

#### Open dependency

- [ ] Expert panel for the query set and for amendment review, and hours per week. Owner: product owner. Needed before M5 (query set) and before M4 (amendment review)

## 18. Glossary

| Term | Meaning |
| --- | --- |
| AAR / AAAR | Authority / Appellate Authority for Advance Ruling |
| As-on date | The date whose law a search result must reflect |
| CBIC | Central Board of Indirect Taxes and Customs |
| CGST / IGST / SGST / UTGST | Central, Integrated, State and Union Territory GST |
| Coverage statement | Per-source statement of what is loaded, up to which date, and known gaps |
| DIN | Document Identification Number on CBIC communications |
| DPDP Act | Digital Personal Data Protection Act, 2023 |
| DRC-01 / 01A | Forms for the demand summary and pre-SCN intimation |
| Good-law status | Whether a judgement still stands (not overruled, reversed or stayed) |
| GSTAT | Goods and Services Tax Appellate Tribunal |
| HSN / SAC | Codes classifying goods / services |
| ITC | Input tax credit |
| Matter | A client engagement or case that groups research, documents and drafts |
| Mention index | Links from every document to the provisions it cites, in any written form |
| Point-in-time law | The text of a provision as it stood on a given date |
| POC | Proof of concept: MVP built first on Docker and Postgres full-text search |
| Production profile | The AWS India region deployment of the MVP |
| Query set | Expert-written research queries, each with a must-find list, used as a release gate |
| RCM | Reverse charge mechanism |
| SCN | Show cause notice |
