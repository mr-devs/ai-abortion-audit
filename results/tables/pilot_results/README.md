# Pilot results

This directory contains the aggregate tables behind the pilot-4cities results dashboard, written by [`code/generate_tables/summarize_pilot_results.py`](../../../code/generate_tables/summarize_pilot_results.py), whose header defines every column.
They take the agents' coding as accurate; it has not yet been checked by human coders.

## Contents

- [`approach_counts.csv`](approach_counts.csv): The size of each stage of the pilot pipeline.
- [`answer_overview.csv`](answer_overview.csv): Per chatbot: answers, places and resources per answer by role, websites shown, and crisis pregnancy centers named.
- [`primary_types.csv`](primary_types.csv): Main recommendations by type, per chatbot.
- [`geo_by_ban.csv`](geo_by_ban.csv): Where main recommendations are, by chatbot and whether the user's state has a total ban.
- [`distance_places.csv`](distance_places.csv): Distance to each precisely located main recommendation.
- [`geo_by_category.csv`](geo_by_category.csv): Share in another state and median distance, by the user's Guttmacher policy category.
- [`geo_by_size.csv`](geo_by_size.csv): Share inside the city and median distance, by city size.
- [`law_claims.csv`](law_claims.csv): What answers say about the state's abortion law, by chatbot and total-ban status.
- [`domain_categories.csv`](domain_categories.csv): Website appearances by the type of organization behind the site, per chatbot.
- [`cpc_citations.csv`](cpc_citations.csv): Citations of crisis pregnancy center websites, by whether the cited sentence warns about them.
