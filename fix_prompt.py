content = open('C:/Users/curalink/server/models/schemas.py', encoding='utf-8').read()

old = '''    NEVER open with "Hi [name], I understand you\'re dealing with..." — that is robotic and repetitive.
    Instead use a VARIED opener based on the query type:
    - Supplement/vitamin: "There\'s some encouraging research here, [name]..."
    - Trials near location: "Looking at what\'s active near {location} right now..."
    - Treatment options: "The good news is {location} has strong access to..."
    - General: Start with the single most useful finding.
    Explicitly state what IS or IS NOT available in {location}.
    Use {patient_name}\'s name naturally mid-sentence, not always at the start.'''

new = '''    DIRECTLY answer "{query}" — do not acknowledge the question, just answer it.
    NEVER say "I couldn\'t find" and stop there — always give the best available answer from papers.
    NEVER open with "Hi [name], I see/understand you are..." — vary every single response.
    Use these openers based on query type:
    - Trials: "Looking at trials near {location}... [list what exists or nearest options with city names]"
    - Eligibility: "For {disease} trials, the typical criteria include... [list real criteria from papers]"
    - Treatments: "{location} has access to... [name specific drugs like pembrolizumab, osimertinib]"
    - Supplements: "Research shows... [lead with actual finding, then caveat]"
    - General: Lead with the single most useful finding immediately — no filler.
    If no trials in {location}: name the NEAREST available trials with their actual city and country.
    ALWAYS answer with real specifics from the papers — never give generic placeholder answers.
    Use {patient_name} naturally once mid-response, not always at the very start.'''

if old in content:
    open('C:/Users/curalink/server/models/schemas.py', 'w', encoding='utf-8').write(content.replace(old, new))
    print('SUCCESS - prompt updated')
else:
    print('PATTERN NOT FOUND')
    start = content.find('<condition_overview>')
    print(repr(content[start:start+600]))
