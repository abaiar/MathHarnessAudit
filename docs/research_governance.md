# Research governance and evidence eligibility

MathHarnessAudit distinguishes software functionality from evidence that is
eligible for a particular manuscript. A validator passing structural checks is
not equivalent to an ethics determination, participant authorization, or proof
of data origin.

## Evidence used by the SoftwareX submission candidate

- provider-free synthetic fixtures and automated tests;
- the frozen 150-episode deterministic aggregate analysis;
- generated tables, figures, and self-hashed manifests;
- build, install, CLI, schema, and CI results produced from the same candidate
  source tree.

The 150-episode analysis is descriptive. It does not rank the three systems and
does not identify causal effects of an architecture or tool call.

## Evidence excluded from manuscript claims

Private human-rating, calibration, identity-linkage, and independent-person
reuse records are excluded from the v0.2.0 paper evidence base. Their current
local history contains unresolved provenance/governance questions, and no
institutional applicability or ethics determination has been supplied. These
materials may be preserved for later resolution, but automated structural
validation cannot make them paper-eligible.

Reintroducing any human-derived result requires, before manuscript use:

1. a documented applicable institutional determination made by the responsible
   human authority;
2. participant/worker consent or other documented lawful basis appropriate to
   the determined pathway;
3. frozen source records with internally consistent origin and role metadata;
4. a reproducible analysis plan that distinguishes agreement from accuracy;
5. author verification of the exact public statements and disclosure boundary.

No repository script may manufacture these facts or convert `pending` into
`passed` based solely on a chat message or file shape.

## External submission blockers

The following facts cannot be completed by software automation:

- publish the final v0.2.0 GitHub tag/release from the accepted source commit;
- create and verify an archival DOI if the authors choose or the editor requests
  one;
- confirm the corresponding author's email/affiliation combination;
- provide the funder name and award identifier, or author-confirm that none
  applies;
- obtain both authors' approval of the exact final manuscript and disclosures.

These items are tracked as external blockers rather than silently marked done.
