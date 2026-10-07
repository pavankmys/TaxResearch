# GST Tax Research Assistant — Functional Specification (FSD)

Draft v0.1 · 7 Oct 2026 · Live version: https://claude.ai/code/artifact/0482c436-e077-485e-a382-44dbb1ec1b65

## 1. Document control and purpose

This FSD defines what the GST Tax Research Assistant must do so it can be frozen and built. It covers functional behaviour, data scope, AI guardrails and non-functional needs; technical architecture follows in a separate TSD.

| Item | Value |
| --- | --- |
| Version | 0.1 (draft for review) |
| Stage | Plan, awaiting freeze |
| Audience | Product owner, domain experts (CA / GST advocate), engineering, QA |
| Jurisdiction | India, Goods and Services Tax (central, integrated, state, UT, compensation cess) |
| Requirement IDs | FR-\<area\>-\<nn\> for functional, NFR-\<nn\> for non-functional |
| Priority key | MVP = first release; P2 = second; P3 = later |

Once frozen, any change to a requirement needs a version bump and sign-off from the product owner.

## 2. Product overview

The product gives GST professionals one place to find the law as it stood on any date, with every answer cited to the source. It then turns that research into planning advice and litigation drafts.

**Problem.** GST law changes constantly. The Acts are amended through Finance Acts, the Rules through notifications, and rates and exemptions through rate notifications. CBIC circulars and a growing body of AAR, High Court, Supreme Court and GSTAT rulings sit on top. Professionals rebuild the position by hand from scattered PDFs and paid databases. That work is slow, misses amendments, and can rely on law that has since been rescinded.

**Vision.** Ask a question in plain language and get a cited answer. The answer reflects the law in force on the relevant date and flags conflicting or pending judgements.

### Personas

| Persona | Primary jobs | What success looks like |
| --- | --- | --- |
| Practising CA / GST consultant | Advisory opinions, client queries, compliance positions | Opinion drafted in hours, not days, with full citations |
| GST advocate / litigation counsel | SCN replies, appeals, writ petitions, precedent search | Finds the right precedents and a first draft fast |
| In-house tax manager | Transaction review, ITC decisions, notice handling | Confident position on day-to-day questions without outside counsel |
| Article assistant / junior associate | Research legwork, summaries, case notes | Correct sources found first time, reviewed by a senior |
| Firm admin / knowledge manager | Users, matters, internal precedents | Firm knowledge reused across teams |

### Value proposition

- **Point-in-time accuracy:** shows what the law said on the transaction date, not only today.
- **Grounded answers:** every claim links to the section, rule, notification, circular or paragraph of a judgement.
- **Research to output:** turns research into opinions, notice replies and appeal grounds in the firm's format.
- **Stays current:** alerts when a change in law or a new ruling affects a saved matter.

## 3. Scope

Release 1 covers Indian GST research with cited answers and a basic matter workspace. Planning and litigation drafting follow in later phases (section 16).

### In scope

- Central GST law: CGST, IGST and UTGST Acts, the Compensation to States Act, and their Rules
- CBIC notifications in every series (Central Tax, Central Tax (Rate), Integrated Tax, Integrated Tax (Rate), UT Tax, Compensation Cess), plus circulars, instructions, orders and Removal of Difficulties Orders
- GST Council meeting recommendations and press releases
- Judgements and rulings: Supreme Court, High Courts, GSTAT, AAR and AAAR
- Firm-uploaded documents: client SCNs, orders, contracts, internal opinions (private to the firm)
- Research Q&A, planning aids, litigation aids, matter workspace, alerts, export

### Out of scope (Release 1)

- Filing returns or any GSTN integration
- Pre-GST laws (excise, service tax, VAT), except where transition provisions or judgements cite them
- Customs, income tax and other direct taxes
- Languages other than English (Hindi and regional-language judgements may follow later)
- Giving final legal advice: outputs support a professional and do not replace one

### Assumptions

- Users are qualified professionals or work under one, and review outputs before use.
- Primary sources are publicly available and may be lawfully collected and stored. Judgements come from court sites or a licensed reporter feed.
- State GST Acts mirror the CGST Act closely enough to map section by section. State-specific notifications are handled as a separate corpus.

### Constraints and dependencies

- Government portals change layout without notice, so scrapers need monitoring and manual fallback.
- Some older notifications and orders are scanned PDFs that need OCR.
- Answers depend on a large language model, so citation checks are mandatory (section 11).
- Personal and client data must comply with India's DPDP Act, 2023.

## 4. Content corpus and source hierarchy

Every document is tagged with its authority level, so answers rank binding law above guidance and guidance above commentary. When sources conflict, the system shows the higher authority first and names the conflict.

| Rank | Source type | Examples | Binding effect | Update frequency |
| --- | --- | --- | --- | --- |
| 1 | Constitution | Art. 246A, 269A, 279A, 286, 366(12A) | Supreme | Rare |
| 2 | Acts | CGST, IGST, UTGST, Compensation Acts; amendments through Finance Acts | Binding | Each Finance Act |
| 3 | Supreme Court judgements | Interpretation of GST provisions and vires challenges | Binding on all | Weekly |
| 4 | Rules | CGST Rules 2017, IGST Rules 2017 | Binding unless ultra vires | Monthly |
| 5 | Notifications | Rate, exemption, procedure, due-date and RCM notifications | Binding (delegated law) | Weekly |
| 6 | High Court judgements | Writs on ITC, refunds, SCN procedure | Binding in that state; persuasive elsewhere | Daily |
| 7 | GSTAT orders | Appeals under Section 112 | Binding on lower authorities | As issued |
| 8 | Circulars, instructions, orders | CBIC clarifications under Section 168 | Bind officers, not taxpayers or courts | Monthly |
| 9 | AAR / AAAR rulings | Advance rulings under Sections 97 to 101 | Bind only the applicant and its officer; persuasive otherwise | Weekly |
| 10 | Council material, FAQs, press releases | Meeting minutes, recommendations | Persuasive, show intent | After each meeting |
| 11 | Firm content | Internal opinions, precedents | Private, persuasive | As uploaded |

### Rules for the corpus

- **FR-COR-01 (MVP):** Store every document with type, issuing authority, number, date of issue, date in force, and status (in force, amended, superseded, rescinded, struck down, stayed).
- **FR-COR-02 (MVP):** Keep every version of the Acts and Rules as dated text, so the law can be rebuilt as it stood on any date since 1 July 2017.
- **FR-COR-03 (MVP):** Record the jurisdiction of each judgement: court, bench, state.
- **FR-COR-04 (P2):** Add state GST Acts, state notifications and state circulars for the 10 highest-volume states first. The state list will be confirmed at freeze.
- **FR-COR-05 (P2):** Keep firm-uploaded content in a tenant-isolated store. It is never used to answer another firm's questions.

## 5. Ingestion pipeline

Every new source document should be searchable within 24 hours of publication, with its metadata and amendment links checked. Anything the pipeline cannot parse confidently goes to a human review queue and is not published silently.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-ING-01 | Monitor official sources daily: CBIC GST portal, GST Council site, e-Gazette, Supreme Court and High Court sites, GSTAT, AAR/AAAR portals. Configurable per source. | MVP |
| FR-ING-02 | Accept manual uploads (PDF, DOCX, HTML, scanned images) from admins and, for private content, from users. | MVP |
| FR-ING-03 | Extract text from digital PDFs and OCR scanned ones. Store page and paragraph positions so citations point to an exact location. | MVP |
| FR-ING-04 | Split the Acts and Rules into chapter, section, sub-section, clause, proviso and explanation. Split notifications into paragraphs and tables (rate schedules by HSN/SAC). Split judgements into header, facts, issues, arguments, findings and order. | MVP |
| FR-ING-05 | Extract metadata automatically: number, date, series, issuing body, subject, sections referred to, effective date, and HSN/SAC codes. For judgements, also capture parties, court, bench, judges, date, citation, and appeal or writ number. | MVP |
| FR-ING-06 | Detect duplicates across sources, such as the same judgement from a court site and a reporter. Keep one canonical record that lists every source URL. | MVP |
| FR-ING-07 | Detect amending language ("substituted", "inserted", "omitted", "rescinded", "in supersession of"). Propose the change to the target provision with its effective date. | MVP |
| FR-ING-08 | A reviewer approves each proposed amendment before the consolidated text changes. Every approval is logged with the reviewer, time and source. | MVP |
| FR-ING-09 | Rebuild consolidated, point-in-time text of the Acts, Rules and rate schedules from the approved amendments. | MVP |
| FR-ING-10 | Show an ingestion dashboard: documents found, parsed, awaiting review, failed, and source health. Alert when a source stops yielding documents. | MVP |
| FR-ING-11 | Re-run parsing for a document or a whole source after a parser change, with a diff report. | P2 |
| FR-ING-12 | Ingest from a licensed case-law feed through a vendor API if one is contracted. | P2 |
| FR-ING-13 | Ingest Hindi and regional-language judgements with translation. | P3 |

**Acceptance:** a CBIC notification published on day D is searchable by D+1. Its links to the amended rule are shown, and asking for the rule's text on a date before the notification's effective date returns the old text.

## 6. Knowledge model

The core asset is a linked graph of provisions and the instruments that change or interpret them, each link dated. Search and AI answers use this graph to find everything that bears on a provision at a given date.

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
- **FR-KM-05 (P2):** Classify how one judgement treats another: followed, relied on, distinguished, doubted, overruled, reversed in appeal, or stayed. The model proposes the label and a reviewer approves it before it is shown as settled.
- **FR-KM-06 (P2):** Track appeals for each judgement and flag when a ruling is under appeal or has been reversed: "good law" status.
- **FR-KM-07 (MVP):** Map each provision and judgement to the topic taxonomy, so users can browse by topic and get alerts on it.
- **FR-KM-08 (MVP):** Keep HSN/SAC rate history, so the system can answer "what was the rate on date X, and which notification set it".

**Acceptance:** opening Section 16(4) of the CGST Act shows its text on any chosen date, its amendment history, the circulars on it, and the leading judgements interpreting it, with their good-law status.

## 7. Research and search

Users get one search box that handles keywords, citations and plain-language questions. Results can be filtered and dated, and each answer links back to the exact paragraph it relies on.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-RES-01 | Hybrid search: keyword (exact phrases, Boolean, proximity) plus semantic search across the whole corpus. | MVP |
| FR-RES-02 | Recognise citations: typing "s.16(2)(c) CGST", "Notf 11/2017-CT(R)", "Circular 183/15/2022" or a case name or citation opens that document directly. | MVP |
| FR-RES-03 | Filter by document type, authority, court, state, date range, status (in force or not), topic, HSN/SAC, and outcome (for or against the assessee). | MVP |
| FR-RES-04 | **As-on date:** every search and question accepts a date (default today). Results and answers use the law in force on that date. | MVP |
| FR-RES-05 | Q&A: answer a question in plain language with a short conclusion, the analysis, and numbered citations to provisions, notifications, circulars and judgement paragraphs. Each citation opens the source at the cited paragraph. | MVP |
| FR-RES-06 | Follow-up questions keep the context of the conversation, including the as-on date and facts already given. | MVP |
| FR-RES-07 | Show conflicting views side by side, such as High Courts split on an issue or a circular at odds with a judgement. Label which view binds where. | MVP |
| FR-RES-08 | Document reader: highlighted search hits, a version selector for provisions, a "what changed" diff between dates, and a panel of linked documents (section 6). | MVP |
| FR-RES-09 | Judgement summary: headnote-style summary with issues, holding, the provisions applied and the outcome, generated on demand and cached. | MVP |
| FR-RES-10 | Compare two dates for a provision or rate ("Rule 36(4) in Oct 2019 vs Jan 2022"). | P2 |
| FR-RES-11 | Research trail: log the queries, documents opened and answers in a matter, so the trail can be exported as a research note. | P2 |
| FR-RES-12 | Find similar: from a judgement or paragraph, find judgements on the same issue. | P2 |

**Acceptance:** "Is ITC available on a car used for business demos in FY 2018-19?" returns an answer that cites Section 17(5)(a) as it stood before the 1 Feb 2019 amendment and as amended. It points out that the FY falls on both sides of that change and lists the relevant AAR rulings, marked as persuasive only.

## 8. Tax planning assistant

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

Matters are the unit of work. Research, documents and drafts live inside a matter, and the system watches each matter for changes in law that affect it.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-WS-01 | Create matters with client, GSTINs, period, topics and team members. Every query, saved document, note and draft can be filed to a matter. | MVP |
| FR-WS-02 | Save items with annotations: bookmark a document or paragraph and add a private or team note. | MVP |
| FR-WS-03 | Daily updates feed of new notifications, circulars and important judgements, filtered by the user's topics, with a one-line summary each. | MVP |
| FR-WS-04 | Daily or weekly email digest of the updates feed, at the user's choice. | MVP |
| FR-WS-05 | Matter impact alerts: when a new instrument or judgement touches a provision, topic or HSN/SAC linked to an open matter, alert the matter team and explain why it matters. | P2 |
| FR-WS-06 | Deadline tracker: reply dates, hearing dates and appeal limitation from FR-LIT-06, with reminders 7, 3 and 1 days before. | P2 |
| FR-WS-07 | Sharing within the firm by matter, with view or edit rights. Comments and @mentions on notes and drafts. | P2 |
| FR-WS-08 | Export answers, research notes and drafts to DOCX and PDF with the firm's letterhead and a full citation list. | MVP |
| FR-WS-09 | Firm knowledge base: approved internal opinions become searchable for that firm only, tagged as internal. | P2 |

## 11. AI answer quality and guardrails

No AI statement about the law reaches the user without a citation that the system has checked against the stored source. When the corpus does not support an answer, the assistant says so rather than filling the gap.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-AI-01 | Grounding: answers are generated only from passages retrieved from the corpus and the matter's documents. The model's general knowledge may frame the analysis but cannot be the sole support for a legal proposition. | MVP |
| FR-AI-02 | Citation check: before display, every citation is matched to a stored document and paragraph, and the quoted or paraphrased text is checked against it. A citation that fails is removed and the claim it supported is marked "unsupported". | MVP |
| FR-AI-03 | No invented authorities: a case name, notification or circular number that is not in the corpus is never shown as a citation. | MVP |
| FR-AI-04 | Temporal check: each cited provision or notification must have been in force on the as-on date. If not, the answer says so explicitly. | MVP |
| FR-AI-05 | Status check: cited circulars and judgements show their status (withdrawn, stayed, overruled, under appeal) inline. | MVP for circulars, P2 for judgements |
| FR-AI-06 | Confidence label per answer: High (settled, binding source), Medium (persuasive or split), Low (little or no authority). A Low answer suggests what to check next. | MVP |
| FR-AI-07 | Quote exactly: text in quotation marks must match the source word for word. | MVP |
| FR-AI-08 | Disclaimer on every answer and export: research aid, not legal advice; verify before reliance. | MVP |
| FR-AI-09 | Feedback: thumbs up or down plus a reason on each answer and citation. Flagged items go to an expert review queue. | MVP |
| FR-AI-10 | Privacy: client documents are not used to train models. The model provider must contractually agree to zero retention. | MVP |
| FR-AI-11 | Prompt safety: text inside uploaded documents is treated as data, never as instructions to the assistant. | MVP |
| FR-AI-12 | Model versioning: every answer stores the model, prompt version and retrieved passages, so it can be reproduced in an audit. | MVP |

## 12. User roles, permissions and admin

The product is multi-tenant: each firm is a tenant, and roles control access within it. A separate platform team, not firm users, curates the shared legal corpus.

| Role | Scope | Can do |
| --- | --- | --- |
| Platform content editor | All tenants (shared corpus) | Approve ingestion, amendments, metadata and judgement treatment; fix errors |
| Platform admin | All tenants | Manage tenants, plans, sources and model settings; view audit logs |
| Firm admin | Own firm | Manage users, seats, SSO, templates, letterhead and firm knowledge base; view firm usage |
| Partner / senior | Own firm | Everything a professional can, plus approving drafts and internal opinions for the knowledge base |
| Professional | Own firm, assigned matters | Research, plan, draft, create matters, share within the firm |
| Junior / article | Own firm, assigned matters | Research and draft. Exports carry a "not reviewed" watermark until a senior approves them. |
| Read-only / client viewer (P3) | Shared matter only | View exported, approved outputs |

- **FR-ADM-01 (MVP):** Email and password login with MFA. SSO (SAML / OIDC) in P2.
- **FR-ADM-02 (MVP):** Matter-level access control. A user sees only matters they are a member of, plus firm-wide items.
- **FR-ADM-03 (MVP):** Audit log of logins, document uploads, exports, sharing and admin changes, kept for 7 years.
- **FR-ADM-04 (P2):** Usage dashboard per firm: queries, active users, drafts and exports.
- **FR-ADM-05 (P2):** Subscription plans with seat counts and usage limits. Billing integration is in scope; payment collection uses a third-party gateway.

## 13. Non-functional requirements

The targets below are proposed starting values to confirm at freeze. They assume up to 5,000 named users and a corpus of about 500,000 documents in the first year.

| ID | Area | Requirement |
| --- | --- | --- |
| NFR-01 | Search speed | Keyword or citation search returns results in under 1.5 s at p95 |
| NFR-02 | Answer speed | Q&A starts streaming within 4 s and completes within 30 s at p95 |
| NFR-03 | Drafting speed | SCN reply or opinion draft is ready within 3 minutes |
| NFR-04 | Freshness | New official documents are searchable within 24 h; consolidated text is updated within 48 h of approval |
| NFR-05 | Availability | 99.5% monthly, excluding announced maintenance |
| NFR-06 | Scale | 200 concurrent users at launch; the design must grow to 10x without a re-architecture |
| NFR-07 | Data residency | All customer data and the corpus stored in India |
| NFR-08 | Privacy | DPDP Act 2023 compliance: consent, purpose limitation, data-principal rights, breach notification |
| NFR-09 | Security | TLS 1.2+ in transit, AES-256 at rest, tenant isolation, OWASP ASVS L2, annual third-party penetration test |
| NFR-10 | Retention | Firm data kept for the life of the subscription plus 90 days, then deleted. Firms can export all their data. |
| NFR-11 | Auditability | Every AI answer is reproducible from its stored inputs (FR-AI-12) |
| NFR-12 | Accessibility | WCAG 2.1 AA for the web app |
| NFR-13 | Platforms | Latest two versions of Chrome, Edge, Safari and Firefox; responsive down to tablet. A mobile app is out of scope for Release 1. |
| NFR-14 | Backup / DR | Daily backups, RPO 24 h, RTO 8 h |
| NFR-15 | Cost control | Per-tenant tracking of AI usage cost, with configurable limits |

## 14. Key user journeys

These six journeys define "done" for each phase. Each is tested end to end with the acceptance criteria shown.

| # | Journey | Persona | Phase | Acceptance criteria |
| --- | --- | --- | --- | --- |
| UJ-1 | Ask a dated question: "Was RCM applicable on legal services to a business entity in Aug 2018?" | Consultant | MVP | Answer cites the RCM notification in force on that date, with every citation opening at the right paragraph; confidence shown; exported to DOCX in under 3 clicks |
| UJ-2 | Trace a provision: open Rule 36(4) and see every version and amending notification | Junior | MVP | Version timeline is complete since insertion; diff between any two dates; linked circulars and judgements listed |
| UJ-3 | Find the HSN rate on a date: "rate for HSN 8703 on 15 Mar 2021, and source" | In-house | MVP | Correct rate and cess, with notification number and entry; rate history shown |
| UJ-4 | Daily update: new circular on a followed topic | Consultant | MVP | Appears in the feed and digest within 24 h, with a one-line summary and topic tags |
| UJ-5 | Plan a transaction: describe a cross-border service arrangement, compare two structures | Consultant | P2 | Issue list, place-of-supply steps, ITC view, scenario table, risk ratings, opinion draft in the firm template |
| UJ-6 | Respond to an SCN: upload a Section 74 SCN, get defects, precedents and a reply draft | Advocate | P2 | Demand extracted correctly; procedural defects flagged with provisions; at least 5 relevant precedents with status; editable reply draft; due date added to the tracker |

Each journey also has a negative test. The question asks about something the corpus does not cover, and the assistant must say it lacks authority and not invent any.

## 15. Success metrics and evaluation

Release quality is measured against a golden set of 300 expert-written questions with model answers and required citations. The set is built with practising GST professionals before MVP development starts. No release ships if a release-gate metric is below target.

| Metric | How measured | MVP target | Gate? |
| --- | --- | --- | --- |
| Citation validity | Share of shown citations that exist and support the claim (expert check) | ≥ 99% | Yes |
| Invented authorities | Citations to documents that do not exist | 0 | Yes |
| Answer correctness | Expert grades the conclusion correct / partly correct / wrong on the golden set | ≥ 85% correct, ≤ 3% wrong | Yes |
| Temporal correctness | Dated questions answered with law in force on that date | ≥ 95% | Yes |
| Required-citation recall | Share of the expert's must-cite sources found by the answer | ≥ 80% | No |
| Ingestion freshness | Official documents searchable within 24 h | ≥ 95% | No |
| Metadata accuracy | Sample audit of number, date, status and section links | ≥ 98% | No |
| Adoption | Weekly active users ÷ paid seats, 90 days after launch | ≥ 60% | No |
| Time saved | User survey: research time vs previous method | ≥ 50% reduction reported | No |
| Satisfaction | Thumbs-up rate on answers | ≥ 80% | No |

The golden set is versioned and re-run on every model, prompt or retrieval change.

## 16. Release phasing

The MVP proves the hardest part, trustworthy point-in-time research, before any drafting is built on top of it. Each later phase starts only when the previous phase passes its quality gate (section 15).

| Phase | Focus | Contents | Gate to next phase |
| --- | --- | --- | --- |
| MVP (Release 1) | Research core | Acts, Rules, notifications; circulars and case law; point-in-time law and HSN rates; cited Q&A and search; updates feed and digest; matters and DOCX/PDF export | Gate 1: MVP release gates met (citations ≥ 99%, correctness ≥ 85%) |
| P2 (Release 2) | Planning and litigation | Transaction analysis; classification, place of supply, ITC; scenario comparison; SCN analysis and reply; precedents with good-law status; state GST, alerts, SSO | Gate 2: drafts rated usable in ≥ 70% of 50 expert scenarios |
| P3 (Release 3) | Depth and reach | Appeal and writ drafting; case-law compilations; regional-language rulings; client viewer access | — |

Feature IDs marked MVP, P2 and P3 in sections 4 to 12 map to these phases. Calendar dates and team size are set at freeze.

## 17. Risks, open questions and decisions for freeze

The FSD can be frozen once the eight decisions below are made. The risks stay on the register through delivery.

### Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Wrong or invented legal authority in an answer | Professional liability, loss of trust | Citation check (FR-AI-02/03), golden-set gate, disclaimer, feedback loop |
| Missed or misapplied amendment gives the wrong point-in-time law | Wrong advice | Human approval of amendments (FR-ING-08); temporal tests in golden set |
| Court and government sites change or block scraping | Stale corpus | Source-health alerts, manual upload fallback, licensed feed option |
| Copyright or licence limits on reported judgements and headnotes | Legal exposure | Use court-issued copies; generate our own summaries; licence a reporter only if needed |
| Client confidential data leaked through the AI provider | Regulatory and reputational harm | Zero-retention contract, India region, tenant isolation, DPDP compliance |
| Volume of AAR and HC rulings outruns editorial review | Treatment labels lag | Model-proposed labels with reviewer queue; prioritise SC and HC |
| Users rely on outputs without review | Liability | Watermarks for unreviewed drafts, confidence labels, terms of use |

### Decisions needed

- [ ] Target customer for MVP: small and mid-size CA firms, large firms, or corporate tax teams?
- [ ] Case-law source: court sites only, or license a reporter feed from day one?
- [ ] States in scope for P2 (proposed: top 10 by GST collection)
- [ ] AI model provider and hosting, given the India data residency requirement
- [ ] Pricing model: per seat, per query volume, or tiered
- [ ] Who forms the expert panel for the golden set and editorial review, and how many hours a week?
- [ ] Whether firm-uploaded documents can be used to improve shared features (default proposed: no)
- [ ] Brand and product name

## 18. Glossary

| Term | Meaning |
| --- | --- |
| AAR / AAAR | Authority / Appellate Authority for Advance Ruling |
| As-on date | The date whose law an answer must apply |
| CBIC | Central Board of Indirect Taxes and Customs |
| CGST / IGST / SGST / UTGST | Central, Integrated, State and Union Territory GST |
| DIN | Document Identification Number on CBIC communications |
| DPDP Act | Digital Personal Data Protection Act, 2023 |
| DRC-01 / 01A | Forms for the demand summary and pre-SCN intimation |
| Golden set | Expert-written test questions with model answers, used as a release gate |
| Good-law status | Whether a judgement still stands (not overruled, reversed or stayed) |
| GSTAT | Goods and Services Tax Appellate Tribunal |
| HSN / SAC | Codes classifying goods / services |
| ITC | Input tax credit |
| Matter | A client engagement or case that groups research, documents and drafts |
| Point-in-time law | The text of a provision as it stood on a given date |
| RCM | Reverse charge mechanism |
| SCN | Show cause notice |
