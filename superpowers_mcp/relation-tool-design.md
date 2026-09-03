

# Relations

## Relation Reason Vocabulary

| Reason Pair                     | Relation                                 |
| ------------------------------- | ----------------------------------------- |
| `produces`, `produced_from`     | research ⇄ decision                      |
| `supersedes`, `superseded_by`   | new decision ⇄ old decision              |
| `promoted_to`, `derived_from`   | decision ⇄ architecture/domain/invariant |
| `composes`, `part_of`           | architecture ⇄ domain                    |
| `enforces`,`enforced_by`        | invariant ⇄ domain                       |
| `references`, `referenced_by`   | any ⇄ any                                |
> **Pairs of Relation reason Vocabulary are exposed as enum, Agent have to choose the reason from pairs and provide the desc and the target URI's (as something like 'primary ' and 'secondry' ) and MCP itself wisely creates the relations.**

## Ideal Relation Graph
```
		                Research
		                   ⇄
		        produces / produced_from
				            ⇄
				         Decision
           ⇄                           	⇄
supersedes / superseded_by          promoted_to / derived_from
         ⇄                                /     |      \
      Decision                           ▼       ▼       ▼
                                  Architecture Domain Invariant
                                       ⇄         ⇄
                                  composes/    enforces/
                                  part_of      enforced_by 
```
## Relation Creation Strategy
Get the input from the agent as something like:

```json
{
  "primary": "viking://resources/project/architecture/*.md",
  "secondary": "viking://resources/project/domains/**/*.md"
  "reason": "composes/part_of",
  "desc": "Lorem ipsum dolor sit amet."
}
```

Store natively in OpenViking as:

```json
{
  "uri": "viking://resources/project/domain/**/*.md",
  "reason": "composes, Lorem ipsum dolor sit amet."
}
```
And:

```json
{
  "uri": "viking://resources/project/architecture/*.md",
  "reason": "part_of, Lorem ipsum dolor sit amet."
}
```

The parsing rule should be deliberately simple:

```text
before first comma  -> reason
after first comma   -> desc
```

So this:

```text
derived_from, changes quorum requirement from 4 to 5
```

becomes:

```json
{
  "reason": "derived_from",
  "desc": "changes quorum requirement from 4 to 5"
}
```

And this is important: **the description can contain additional commas**. Only split once.

So the native convention is:

```text
<relation_type>, <description>
```
## Relation Removal Strategy

For removing the relation, get the input from agent as:
```json
{
  "primary": "viking://resources/project/architecture/*.md",
  "secondary": "viking://resources/project/domains/**/*.md"
}
```
And remove the two side relations.
