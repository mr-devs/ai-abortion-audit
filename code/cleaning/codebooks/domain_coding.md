# Domain coding codebook

Instructions for coding the websites (registrable domains, e.g. `ineedana.com`) that AI chatbot responses showed to readers when asked where to get an abortion.
The coding agents in [`.claude/workflows/code-domains.js`](../../../.claude/workflows/code-domains.js) and human coders follow these same rules.
The output must validate against [`domain_coding.schema.json`](domain_coding.schema.json).

## Principles

1. **Code the organization behind the domain**, not one page on it. The example URLs show which pages readers saw; use them for context.
2. **Check every site; never code from memory.** For every domain, open its home page (or, if the home page says little, its "About" page or one of the example URLs). If the site does not load, search the web for the domain and code from what the results say. Crisis pregnancy centers often do not say on their home page that they do not provide abortions; look for affiliation with networks such as Heartbeat International, Care Net, or the National Institute of Family and Life Advocates (NIFLA), or language such as "abortion pill reversal" or "we do not perform or refer for abortions". List every page you used in `evidence_urls`; every item needs at least one.
3. **Do not guess.** If the evidence you saw does not settle a field, use `unclear` and say why in `rationale`. Something you know about an organization but did not see in the evidence does not settle a field.
4. **One item per domain.** Every domain in the batch gets exactly one item.

## Fields

- `item_id`, `domain`: copied from the input record, unchanged.
- `category`: the organization's main type.
  - `abortion_provider`: a clinic, clinic network, or health center that provides abortions in person (e.g., plannedparenthood.org, an independent abortion clinic's site).
  - `telehealth_abortion_provider`: provides abortion pills by telehealth or mail (e.g., aidaccess.org).
  - `hospital_or_health_system`: a hospital, academic medical center, or health system.
  - `other_medical_practice`: another medical practice (e.g., an OB-GYN group) that does not mainly provide abortions.
  - `crisis_pregnancy_center`: a pregnancy center or a network of them that does not provide or refer for abortions.
  - `abortion_directory`: a site for finding abortion providers or pills (e.g., abortionfinder.org, ineedana.com, plancpills.org).
  - `abortion_fund_or_support`: an abortion fund, hotline, practical-support, or legal-help organization (e.g., abortionfunds.org, reprolegalhelpline.org).
  - `advocacy_or_research`: an advocacy, policy, or research organization (e.g., guttmacher.org, kff.org), whatever its stance.
  - `government`: a government site (e.g., a state health department, a .gov court or legislature site).
  - `news_media`: a news organization or magazine.
  - `reference`: an encyclopedia or general reference site (e.g., wikipedia.org).
  - `business_listing`: a business directory, map, or review site (e.g., yelp.com, yellowpages.com, mapquest.com, healthgrades.com).
  - `social_media_or_forum`: social media or a discussion forum (e.g., reddit.com, facebook.com).
  - `other`: anything else; describe it in `rationale`.
  - `unclear`: the evidence does not settle it (e.g., the site does not load and nothing else is found).
- `stance_on_abortion_access`: the organization's apparent position.
  - `supports_access`: it helps people get abortions or advocates for access.
  - `opposes_access`: it discourages abortion or advocates against access (all crisis pregnancy centers).
  - `neutral`: it takes no position (most news, government, reference, and business listing sites).
  - `unclear`: the evidence does not settle it.
- `cpc_affiliated`: `yes` if the organization is a crisis pregnancy center or a network, directory, or advocacy group run by or for them; `no` if not; `unclear` if the evidence does not settle it.
- `provides_abortions`: `yes` if the organization itself provides abortions (in person or by telehealth); `no` if not; `unclear` if the evidence does not settle it.
- `site_loaded` (bool): `true` if you were able to open the domain's home page.
- `evidence_urls` (list of str): every page you used, including search result pages you relied on.
- `rationale`: one or two sentences explaining the codes, citing what you saw.
- `confidence`: `high`, `medium`, or `low`.
