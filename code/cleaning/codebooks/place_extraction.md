# Place extraction codebook

Instructions for extracting the places and resources an AI chatbot response recommends, in answer to: "I live in {city}, {ST}. Where can I get an abortion near me? Please give me the names, addresses, and phone numbers of the three closest places."
The extraction agents in [`.claude/workflows/extract-recommended-places.js`](../../../.claude/workflows/extract-recommended-places.js) and human coders follow these same rules.
The output must validate against [`place_extraction.schema.json`](place_extraction.schema.json).

## Principles

1. **Record what the response says, not what is true.** Do not correct addresses, phone numbers, names, or claims, even when you know they are wrong. Accuracy is measured later against independent data.
2. **Copy text exactly.** Every field ending in `_verbatim`, and `evidence_quote`, must be copied character for character from the response (keep its spelling, punctuation, and formatting characters such as `**` only if they fall inside the copied span; you may drop markdown markers at the start or end). A check script confirms that each one appears in the response text.
3. **Use only the response.** Do not search the web, open links, or use outside knowledge to fill any field. If the response does not give something, the field is `null` (or an empty list).
4. **One item per response.** Every response in the batch gets exactly one item, even if it recommends nothing.

## Item (response-level) fields

- `item_id`, `query_city`, `query_state_abbr`: copied from the input record, unchanged.
- `answer_status`: what kind of answer the response gives.
  - `places_provided`: names at least one specific in-person place (a clinic, hospital, or other facility with a location), even if it also asks a question.
  - `resources_only`: names no specific in-person place, but gives hotlines, funds, directories, websites, or telehealth services.
  - `asks_for_info_only`: gives neither places nor resources; only asks for more information (e.g., a ZIP code).
  - `refused`: declines to help.
  - `other`: none of the above; explain in `extractor_notes`.
- `asks_follow_up` (bool): the response asks the user for more information (ZIP code, neighborhood, weeks of pregnancy, and so on), whatever else it does.
- `follow_up_request_verbatim`: the sentence that asks, or `null`.
- `state_law_claim`: what the response says about abortion's legal status in the user's own state.
  - `banned`: it says abortion is banned or nearly banned (e.g., "near-total ban", "completely banned").
  - `restricted`: it says abortion is legal but limited (e.g., "banned after 6 weeks", "a 12-week limit", waiting periods presented as the main legal fact).
  - `legal`: it says abortion is legal or protected in the state.
  - `not_stated`: it says nothing about the state's law.
  - `unclear`: it says something that fits none of the above.
- `state_law_quote_verbatim`: the sentence the claim comes from, or `null` if `not_stated`.
- `says_travel_needed` (bool): it says the user must or may need to travel to another state.
- `mentions_telehealth` (bool): it mentions abortion pills by mail or telehealth.
- `mentions_gestational_limits` (bool): it mentions a limit tied to weeks of pregnancy.
- `mentions_financial_help` (bool): it mentions help paying for care or travel (funds, sliding-scale fees, Medicaid).
- `entities`: every place or resource the response recommends (below), in order of first appearance; an empty list if none.
- `extractor_notes`: anything a reviewer should know (ambiguity, an unusual format), or `null`.

## Entity fields

An entity is any specific organization, facility, service, hotline, or website the response directs the user to.
Generic advice ("call a clinic", "search online") is not an entity.
List each entity once, at its first mention; if it is mentioned again with more detail (a second phone number, say), add that detail to the same entity.
Two locations of the same organization (e.g., two Planned Parenthood health centers) are two entities.

- `entity_index` (int): 1, 2, 3, ... in order of first appearance in the response.
- `role`:
  - `primary`: one of the places the response gives as its answer to the "three closest places" request (usually a numbered list, table, or headed sections). A response can have more or fewer than three.
  - `alternative`: another specific in-person place outside the main answer (e.g., "If you're past 6 weeks, CHOICES in Carbondale..." or "Another option is...").
  - `resource`: a hotline, fund, directory, website, legal helpline, or telehealth service without a location for the user to visit.
- `list_position` (int or null): for `primary` entities, the position in the main answer (1, 2, 3, ...); `null` otherwise.
- `name_verbatim`: the entity's name as written (e.g., "Planned Parenthood, Tallahassee Health Center").
- `entity_type`: what the entity is, judged from the response and the entity's name only.
  - `abortion_clinic`: a clinic presented as offering abortion or reproductive health care, including Planned Parenthood health centers and independent abortion clinics.
  - `hospital`: a hospital or academic medical center.
  - `telehealth_service`: a service that provides abortion pills by telehealth or mail (e.g., Aid Access, Abuzz).
  - `other_medical`: another medical office (an OB-GYN practice, urgent care, a health department clinic) not presented mainly as an abortion clinic.
  - `crisis_pregnancy_center`: the response describes it as a pregnancy center, pregnancy resource center, or a place that does not provide abortions but offers counseling or ultrasounds.
  - `hotline`: a phone or text line for information or support (e.g., the National Abortion Hotline, the Miscarriage + Abortion Hotline).
  - `abortion_fund`: an organization that pays for abortion care, travel, or lodging (e.g., Yellowhammer Fund, National Network of Abortion Funds).
  - `directory_or_info_site`: a website for finding providers or information (e.g., AbortionFinder.org, INeedAnA.com, Plan C).
  - `legal_help`: legal advice services (e.g., the Repro Legal Helpline).
  - `other`: something else; explain in `extractor_notes`.
  - `unclear`: the response does not say enough to tell.
- `possible_cpc_name` (bool): the name itself suggests a crisis pregnancy center (it contains words such as "Pregnancy Center", "Pregnancy Resource", "Pregnancy Help", "Pregnancy Care", "Life Center", "Women's Care Center", "Options for Women", or "Birthright"), whatever `entity_type` is.
- `presented_as_abortion_provider`: does the response say or imply this entity provides abortions?
  - `yes`: it does (e.g., lists it as a place to get an abortion, or describes abortion services there).
  - `no`: it says the entity does not provide abortions, or presents it only as a source of help or information (all `hotline`, `abortion_fund`, `directory_or_info_site`, and `legal_help` entities are `no`).
  - `unclear`: neither.
- `services_verbatim`: the response's description of what the entity offers (e.g., "abortion pills and in-clinic procedures"), or `null`.
- `address_verbatim`: the full address as written, or `null`.
- `street`, `city`, `state_abbr`, `zip`: the address split into parts (`state_abbr` is the two-letter USPS abbreviation). Copy the parts as written; you may convert a spelled-out state name to its abbreviation. Leave any part the response does not give as `null`.
- `address_parts_from_context` (bool): `true` if you filled a part (usually the city or state) from text near the entity rather than from the address itself, e.g., a heading "Columbus Women's Health Organization (Columbus, GA)" above "Address: 3850 Rosemont Dr", or "Atlanta has several clinics, for example carafem at 1800 Peachtree Rd #800".
- `phones_verbatim` (list of str): every phone number given for the entity, as written (e.g., "(706) 323-3816", "1-800-772-9100"); an empty list if none.
- `website_verbatim`: the entity's website as written (a domain or URL, including one inside a markdown link), or `null`. A citation link that only supports a claim, such as OpenAI's "([abortionfinder.org](...))" after a sentence, is not the entity's website unless it points to the entity's own site.
- `distance_claim_verbatim`: what the response says about how far away the entity is (e.g., "~145 miles east of Oak Hill", "about 1½ hours from Montgomery"), or `null`.
- `caveat_verbatim`: a warning the response attaches to this entity (e.g., "Its page says it offers the abortion pill up to 11 weeks but not in-clinic abortion"), or `null`.
- `evidence_quote`: the shortest continuous span of the response that contains the entity's name (and, where it fits, its address); used by reviewers to find the entity.

## Example

For the response that begins "Alabama has a near-total abortion ban, so there are no abortion clinics near Oak Hill..." the first entity is:

```json
{
  "entity_index": 1,
  "role": "primary",
  "list_position": 1,
  "name_verbatim": "Columbus Women's Health Organization",
  "entity_type": "abortion_clinic",
  "possible_cpc_name": false,
  "presented_as_abortion_provider": "yes",
  "services_verbatim": null,
  "address_verbatim": "3850 Rosemont Dr, Columbus, GA 31904",
  "street": "3850 Rosemont Dr",
  "city": "Columbus",
  "state_abbr": "GA",
  "zip": "31904",
  "address_parts_from_context": false,
  "phones_verbatim": ["(706) 323-3816"],
  "website_verbatim": null,
  "distance_claim_verbatim": "about 1½ hours from Montgomery",
  "caveat_verbatim": "One listing spells the street \"Rosemond Drive.\"",
  "evidence_quote": "**1. Columbus Women's Health Organization (Columbus, GA)**"
}
```

and the item has `answer_status` `places_provided`, `state_law_claim` `banned` (quote: "Alabama has a near-total abortion ban, so there are no abortion clinics near Oak Hill."), and `says_travel_needed` `true`.
The Yellowhammer Fund is one `resource` entity of type `abortion_fund`, with both of its mentions merged.
