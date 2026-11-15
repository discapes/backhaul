# Backhaul

An RL environment for AfterQuery's "Break the Agent" challenge. The agent runs the Baltic desk of a freight forwarder for a 10-week season and buys ship space in sealed-bid auctions against other shippers who price space the way economists would.

## Reproduce the results

Requires Docker and Harbor (`uv tool install harbor`). One command runs everything the judging needs: the reference run, the do-nothing and stop-early baselines, and three agent runs with OpenCode over MCP.

```bash
BACKHAUL_SEED=1 ./eval.sh -a opencode -m <provider/model>
```

It prints one line per run. With Kimi K3.1 Pro on Verda's OpenAI-compatible endpoint (`-a opencode -m verda/kimi-k3-1-pro --base-url https://inference.verda.com/v1 --api-format openai_chat_completions --api-key-name VERDA_INFERENCE_KEY`) it printed:

```
reference   reward 0.913  cash    357,842  weeks played 10
do-nothing  reward 0.000  cash   -280,500  weeks played 0
stop-early  reward 0.050  cash   -245,295  weeks played 2
agent       reward 0.858  cash    319,220  weeks played 10
agent       reward 0.790  cash    271,690  weeks played 10
agent       reward 0.796  cash    276,031  weeks played 10
```

`BACKHAUL_SEED=1` replays the market behind every number in this README, so the reference, do-nothing and stop-early lines come out exactly as above; agent runs vary with the model's sampling. Without it, every container draws a random seed so that an agent which finds this source still cannot know the rival bids. The reference then scores 0.91–0.93, do-nothing 0 and stopping after week 2 about 0.05. Job output, including the agent trajectories and each run's `verifier/score.json` with the week-by-week auction results and its seed, is written to `jobs/`.

The runs are ordinary Harbor jobs, so they can also be started one by one:

```bash
harbor run -p task -a oracle                         # reference
harbor run -p task -a nop                            # do nothing
harbor run -p task -a oracle --ae REFERENCE_WEEKS=2  # stop early
harbor run -p task -a opencode -m <provider/model>   # agent
```

## Why this setting

A ship that carries paper from Kotka to Lübeck has to sail back anyway. With far more space than cargo on the way back, that space sells for little more than the carriers' cost of loading a ton, whatever the voyage cost to run. Prices are bids that shippers make against each other, and they depend on what the other bidders know. An agent that is going to buy and sell on someone's behalf has to reason this way, and Backhaul tests whether it does.

The environment turns this into decisions that can be scored:

- **Backhaul:** northbound demand is far below capacity, so northbound space clears just above the carriers' $4/t handling cost. Bidding a share of fuel and charter costs overpays.
- **Scarcity:** southbound demand exceeds capacity in most weeks, so the price is set by the value of the marginal shipper who misses out. Carrier costs have nothing to do with it.
- **Planning across weeks:** a pulp-mill shutdown (weeks 3–4) leaves southbound space nearly free, a drydocked ship (weeks 6–7) makes it scarce, a pre-holiday surge (weeks 8–9) and a ship chartered in late (announced in week 6) move it again. Cargo with flexible windows should move to the cheap weeks, and offers are worth accepting or declining depending on where prices will be, not where they were.
- **Pay-as-bid:** every winning bid pays its own price, and the auction fills from the top, so an agent's own high bids take space ahead of its low ones. Bidding "safely high" just transfers money to the carriers. Bidding well means estimating what the other shippers will bid.
- **Fuel news:** fuel prices rise 60% in week 5. That raises the cost of a sailing and leaves the cost of an extra ton unchanged, so space prices should not move.

All the information needed is in the tools: carrier costs, the 10-week outlook of capacity and other shippers' demand, the range of their values, the auction rules, and each week's clearing prices.

## The environment

A Harbor task (`task/`). The market runs as an MCP sidecar container (`task/environment/market/`), so the agent can only act through the tools:

| Tool | Does |
|---|---|
| `market_brief` | Rules, carrier costs, the outlook and the news to date |
| `get_status` | Week, cash, orders, open offers, this week's bids, every past auction result |
| `accept_offer` | Accept a customer offer (only in the week it is offered) |
| `place_bids` | Set this week's bids (price $/t, tons) for one sailing |
| `advance_week` | Run both auctions, load cargo, charge penalties for missed deadlines |

A season is a `Scenario` in `sim.py`: the vessels in service each week, the other shippers' demand, the news, the fuel price and the agent's orders and offers. The Harbor task plays `TASK`, the season described above. `random_scenario(seed)` generates other seasons from the same rules, with different event timing and size, drydocked vessel, late charters, fuel shocks, northbound rushes in some seasons, and different orders; it produces training experience that never contains the task's own season.

Other shippers' bids come from a seed and the published outlook and do not react to the agent, so the full-information optimum can be computed exactly for each run. Each container draws a random seed, so an agent that has read this source still cannot know the rival bids; set `BACKHAUL_SEED` to replay one market. Every `score.json` records its seed.

## Reward

`reward = (cash − do_nothing) / (optimum − do_nothing)`, clipped to [0, 1].

- `do_nothing` is the cash after paying penalties on every committed order (−$280,500).
- `optimum` is the best cash achievable with full knowledge of every rival bid. It is a mixed-integer program (`optimum.py`) in which each sailing has one price level, each offer is accepted or not, and orders are split across the weeks of their windows. For seed 1 it is $418,806.
- Weeks the agent leaves unplayed are played out with no bids before scoring, so stopping early earns the penalties of unshipped cargo.

The verifier reads the score from the sidecar's `/score` endpoint, which requires a token that exists only in the sidecar and the verifier environment.

## Reference run

`task/solution/reference.py` is a scripted planner. It uses only what the agent sees through MCP. It models each sailing from the outlook: spare space costs the reserve, which it estimates from the lowest clearing price seen. Scarce space costs the value of the marginal shipper, at the quantile of the value range where other shippers' tons fill the capacity, plus a $3 margin. Each week it solves a mixed-integer program over the remaining season to decide which offers to accept and how much cargo to ship when, then bids that week's part of the plan at one price per sailing. Harbor runs it as the oracle agent.

## Results (seed 1)

| Run | Cash after 10 weeks | Reward |
|---|---|---|
| Best possible season (optimum) | $418,806 | 1.000 |
| Reference (oracle) | $357,842 | 0.913 |
| Kimi K3.1 Pro, OpenCode, 6 runs | $265,400–319,220, mean $289,057 | 0.781–0.858, mean 0.814 |
| Claude Fable 5.2, 2 runs | $273,680, $273,250 | 0.793, 0.792 |
| Claude Opus 5.5, 1 run | $222,500 | 0.719 |
| DeepSeek 4.1 Flash, OpenCode | $182,500 | 0.662 |
| Stop after week 2 | −$245,295 | 0.050 |
| Do nothing (nop) | −$280,500 | 0.000 |

The Claude runs played through the same MCP tools from a command-line client outside Harbor, because no Anthropic API key was available for the harness.

## Where the agents lose money

Every model learned that northbound space is cheap: they bid near $5/t northbound from the first week or after one rejected probe, and accepted cheap northbound offers on the grounds that the ships sail anyway. The gap comes from the step after that: modelling the other bidders.

- **Overbidding in pay-as-bid auctions.** In week 3 a pulp mill is shut, southbound space is left over and the other shippers bid $5.16–7.14/t. Every model treated a high bid as insurance, and in a pay-as-bid auction it is a payment:

  | Run | Week 3 southbound bids | Paid | Same tons at the clearing price |
  |---|---|---|---|
  | Kimi K3.1 Pro | $30.01 and $33.50 | $61,765 | $10,440 |
  | Claude Opus 5.5 | ladder $20–36 | $43,200 | $7,740 |
  | Claude Fable 5.2, run B | ladder $10–34 | $44,000 | $10,440 |
  | Claude Fable 5.2, run A | ladder $6–34 | $20,000 | $5,160 |

  Kimi's notes before bidding: `If uniformly valued30-70 and bids equal values, marginal should35.714.` The rules state that the other shippers see the same outlook and bid with it in mind. The reference turns that into a price estimate; the agents did not.
- **Ignoring new information.** Nordic Swan's charter for weeks 9–10 is announced in the brief in week 6. The Opus run and Fable run A stopped reading the brief after week 1 and paid $44–48/t in week 9, which cleared at $36.
- **Anchoring on past prices when judging offers.** O5 pays $49/t for southbound cargo shippable in weeks 8–10. Week 10 has the extra vessel and clears near $30, so O5 earns about $19/t. Kimi declined it in its first three runs, judging it against the $43–47 of recent weeks.
- **Underbidding urgent cargo.** Kimi bid $40 for S1 in week 1, below the $41–44 needed, and missed part of an order with a $30/t penalty.

Each mistake is a decision the agent made with the information in front of it. The reference makes the same decisions from the same tools.

## Training a smaller model on the environment

`train/` fine-tunes Qwen3-4B-Instruct-2507 on experience from the environment and plays it before and after.

- **Policy interface** (`train/policy.py`): one model call per week. The observation is a compact text of the same data `market_brief` and `get_status` return, and the reply is one JSON action (`{"accept": [...], "bids": {"south": [...], "north": [...]}}`). Each move in a reply is applied on its own, as a separate MCP tool call would be, and moves the market refuses are counted.
- **Experience** (`train/gen.py`): the reference planner plays 800 seasons from the scenario generator (`random_scenario`, seeds 1000–1799), each week one example: 8,000 weeks. The task's own season never appears in it.
- **Training** (`train/sft.py`): LoRA (rank 32, all linear layers), one epoch, loss on the action only.
- **Evaluation** (`train/evaluate.py`): greedy decoding, the 30 market seeds of the task's season (1–30), and 30 generated seasons outside the training range (9000–9029).

| Policy | Task season, seeds 1–30 | Generated seasons 9000–9029 |
|---|---|---|
| Qwen3-4B-Instruct, base | 0.000 (mean cash −$1,729,677; 211 refused moves) | 0.002 (−$1,100,383; 198 refused) |
| Qwen3-4B-Instruct + LoRA on 240 generated seasons (2,400 weeks) | 0.687 ($195,723; 0 refused) | 0.690 ($204,997; 0 refused) |
| Qwen3-4B-Instruct + LoRA on 800 generated seasons (8,000 weeks) | **0.831** ($295,971; 0 refused) | **0.843** ($313,501; 0 refused) |
| Reference planner (the expert it learned from) | 0.920 ($357,734) | 0.889 ($338,236) |

The base model's moves go through but lose over a million dollars a season; in week 1, for example, it bids $55–68/t for southbound space that clears at $40.20. After 150 training steps (10 minutes on one RTX PRO 6000) the same model follows the action format in every week and earns money on a season it never saw. With all 8,000 weeks (500 steps, 41 minutes) it reaches 0.831 on the task's season, 90% of the expert's score. For scale, Kimi K3.1 Pro averaged 0.814 on seed 1 through OpenCode and the MCP tools; the fine-tuned model plays through the one-call-per-week interface above, so the numbers are close but not the same test.

To reproduce: `cd train && python gen.py 1000 1240 data/expert-240.jsonl` on any machine (seconds; `1000 1800` writes the full 8,000 weeks), then on a GPU machine run `bash backhaul/train/job.sh data/expert-240.jsonl` from the directory holding `backhaul/`; it trains, then evaluates the base and fine-tuned models with batched `transformers` generation.

## Reward integrity

- The market state lives in a separate container. The agent's only access is the five tools, and the score endpoint needs a token the agent never sees.
- The agent runs as an unprivileged user. Before reading the score, the verifier runs as root, kills every process the agent user left running, and runs Python in isolated mode, so planted modules and leftover processes cannot change the reward.
- Space won is paid for whether or not it is used, bids below the reserve win nothing, and the tool inputs are validated: prices must be above 0 and at most $500/t, tons must be whole numbers between 1 and 20,000, and a sailing takes at most 20,000 t of bids in total.
- Before reading the score, the verifier deletes everything in `/logs/verifier` except its own output log, so a `reward.txt` or `reward.json` the agent wrote there cannot stand if scoring fails.
- Other strategies can try to game the score through the real MCP server: `exploits/run.py` plays each against a fresh seed-1 market and also sends invalid moves.

  ```bash
  uv run --with mcp==2.3.0 --with fastmcp==4.2.0 --with scipy==1.18.1 --with numpy==2.5.4 python exploits/run.py
  ```

  | Strategy | Season cash | Reward |
  |---|---|---|
  | Trade well (reference planner) | $357,842 | 0.913 |
  | Bid the $5 minimum on 20,000 t every sailing | −$84,200 | 0.281 |
  | Accept every offer and bid $5 on 20,000 t every sailing | −$189,600 | 0.130 |
  | Quit after week 2 | −$245,295 | 0.050 |
  | Do nothing | −$280,500 | 0.000 |
  | 50 concurrent `advance_week` calls | −$280,500 | 0.000 |
  | Accept every offer, never bid | −$492,000 | 0.000 |
  | Outbid everyone at $50/t on 20,000 t | −$5,143,000 | 0.000 |

  All 10 invalid moves are refused: negative, fractional or more than 20,000 t; zero, NaN or infinite prices; an unknown leg; an offer from a later week, an order already in the book, a made-up offer. `/score` answers HTTP 401 without the token or with a wrong one.
