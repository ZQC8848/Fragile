"""M2's `rule` path: keyword and pattern rules over the player's input (backend-design.md §4.2).

It is the baseline the trained encoder has to beat, and the offline mock of the `review` LLM role answers
with it, so the whole game runs without a network. Output has exactly the shape of schemas/llm/review.json.

What it can do: split a single text box into channels by quotes, find the addressee, tag discourse acts
sentence by sentence, tag topics and claims, map an action to the closed action table, judge validity
(interaction-design.md §4.2) and propose a rewrite. What it cannot do: translate (non-English input passes
through untranslated), or understand anything its patterns do not name.
"""

from __future__ import annotations

import re
from typing import Any

HOSTS = ("julian", "mia")
NPCS = ("julian", "mia", "nora")

# --------------------------------------------------------------------------- validity
_VALIDITY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("meta", re.compile(
        r"ignore (all |the |your |any )?(previous|prior|above|earlier)|system prompt|\bprompt\b|\byou are an ai\b|"
        r"\bas an ai\b|developer mode|jailbreak|disregard (the|your|all) (rules|instructions)|忽略|系统提示", re.I)),
    ("out_of_scope", re.compile(
        r"\b(stab|shoot|strangle|murder|kill|behead)\w*\b.{0,24}\b(him|her|julian|mia|nora|them|everyone|myself)\b|"
        r"\b(gun|rape|sex|naked|suicide|kill myself|set fire|burn (the|this) (place|flat|apartment)( down)?|smash everything)\b", re.I)),
    ("absurd", re.compile(
        r"\b(fly|flies|flying|levitat\w*|teleport\w*|lightsaber|magic|cast a spell|superpower\w*|turn invisible|"
        r"time travel\w*|dragon|laser beam)\b", re.I)),
    ("npc_speech", re.compile(r"\b(julian|mia|nora)\s*(:|says|said|replies|replied|answers|answered|whispers|shouts|tells me)", re.I)),
    ("npc_action", re.compile(
        r"(?:^|[.;!?]\s*|\b(?:and|then|while)\s+)(julian|mia|nora)\s+(?!and\b|or\b)([a-z]+(?:s|ed))\b", re.I)),
    ("outcome", re.compile(
        r"\b(easily|successfully|manage to|managed to|finally)\b|\band (see|find|discover)\b|"
        r"\b(it|the lid|the door|the crate) (opens|gives way|comes open)\b", re.I)),
    ("perception", re.compile(r"\bi (see|saw|notice|noticed|smell|smelled|hear|heard|spot|spotted|realize|realise|sense)\b", re.I)),
    ("invention", re.compile(
        r"\bi (find|found|discover|discovered|pull out|produce)\b|"
        r"\b(nora|leo|the police) (is|are|has|have) (already )?(here|downstairs|arrived)\b|\bthere is a (gun|body|note|letter)\b", re.I)),
    ("stride_time", re.compile(r"\b(wait|waited|sit|sat|stay|stayed)\b.{0,15}\b(an hour|hours|all night|until morning|for ages)\b", re.I)),
]

VALIDITY_MESSAGES = {
    "npc_action": "You can only decide what you do. \"{span}\" decides what someone else does.",
    "npc_speech": "You can only write your own words. \"{span}\" puts words in someone else's mouth.",
    "outcome": "You can try things, but the story decides how they turn out. \"{span}\" decides the result.",
    "perception": "The story tells you what you notice. Write what you look at or listen for instead of \"{span}\".",
    "invention": "\"{span}\" adds something to the world that isn't there. Look for it instead.",
    "stride": "One step per turn: one change of place and one thing with an object. \"{span}\" does more.",
    "absurd": "\"{span}\" isn't possible in this story.",
    "out_of_scope": "\"{span}\" is beyond what this story can hold.",
    "meta": "That reads as an instruction to the system rather than something you do in the scene.",
}

# --------------------------------------------------------------------------- actions
ROOM_WORDS: list[tuple[str, re.Pattern[str]]] = [
    ("kitchen", re.compile(r"\bkitchen\b", re.I)),
    ("balcony", re.compile(r"\b(balcony|terrace)\b", re.I)),
    ("living", re.compile(r"\b(living ?room|lounge|sitting room|back inside|inside)\b", re.I)),
    ("hall", re.compile(r"\b(hall|hallway|entrance|entryway)\b", re.I)),
    ("bathroom", re.compile(r"\b(bathroom|toilet|loo|washroom|restroom)\b", re.I)),
]

#: first match wins; order matters (phone verbs before `call`, people verbs before `take`)
VERBS: list[tuple[str, re.Pattern[str]]] = [
    ("listen_voicemail", re.compile(r"\bvoicemail\b|\b(listen|play)\w*\b.{0,20}\bmessage\b", re.I)),
    ("decline_call", re.compile(r"\b(decline|reject|ignore|silence|hang up on)\b.{0,15}\b(call|phone|it|her|nora)\b", re.I)),
    ("answer_call", re.compile(r"\b(answer|pick up|take)\b.{0,15}\b(phone|call|it|nora)\b|^\s*answer\b", re.I)),
    ("give_phone", re.compile(r"\b(give|hand|pass|show)\b.{0,25}\bphone\b", re.I)),
    ("text", re.compile(r"\b(text|message|reply to|send)\b", re.I)),
    ("call", re.compile(r"\b(call|dial|ring|phone)\b", re.I)),
    ("take_aside", re.compile(r"\b(take|pull|draw|ask|lead)\b\s+(julian|mia)\b.{0,25}\b(aside|alone|out to|into the|to the)\b", re.I)),
    ("leave", re.compile(r"\b(leave|walk out|go home|head out|out the (front )?door|exit the flat|get out)\b", re.I)),
    ("go_to", re.compile(r"\b(go|goes|walk|head|step|move|come|return|wander|slip|follow \w+)\b", re.I)),
    ("search", re.compile(r"\b(search|rummage|go through|pat down|reach into|check)\b.{0,25}\b(jacket|coat|pocket)", re.I)),
    ("look_out", re.compile(r"\blook\w*\s+(out|down|over)\b|\bout the window\b|\bover the railing\b|\bpeer\w* (out|down)\b", re.I)),
    ("open", re.compile(r"\b(open|unscrew|pry|prise|lift the lid|undo the screws|unseal)\w*\b", re.I)),
    ("hit", re.compile(r"\b(hit|punch|slap|strike)\w*\b", re.I)),
    ("push", re.compile(r"\b(push|shove)\w*\b", re.I)),
    ("grab", re.compile(r"\b(grab|seize|grip)\w*\b.{0,15}\b(julian|mia|nora|arm|wrist|hand|shoulder|collar)\b", re.I)),
    ("hug", re.compile(r"\b(hug|embrace)\w*\b", re.I)),
    ("smell", re.compile(r"\b(smell|sniff)\w*\b", re.I)),
    ("knock", re.compile(r"\b(knock|tap|rap)\w*\b", re.I)),
    ("sit", re.compile(r"\b(sit|sits|sat)\b", re.I)),
    ("drink", re.compile(r"\b(drink|sip|finish my|down my)\w*\b", re.I)),
    ("pour", re.compile(r"\bpour\w*\b", re.I)),
    ("toast", re.compile(r"\b(toast|raise my glass|cheers)\b", re.I)),
    ("eat", re.compile(r"\b(eat|taste|try the)\w*\b", re.I)),
    ("place", re.compile(r"\b(put|place|set|rest)\b", re.I)),
    ("take", re.compile(r"\b(take|grab|pick up|pocket)\w*\b", re.I)),
    ("touch", re.compile(r"\b(touch|feel|run my hand|stroke|lay a hand|put a hand)\w*\b", re.I)),
    ("examine", re.compile(r"\b(look|examine|inspect|study|check|read|glance|stare|peer|watch|eye|search)\w*\b", re.I)),
]

TARGETS: list[tuple[str, re.Pattern[str]]] = [
    ("tools_box", re.compile(r"\btools?\s*box|\btoolbox|\bbox marked tools\b", re.I)),
    ("screwdriver", re.compile(r"\bscrewdriver\b", re.I)),
    ("drill", re.compile(r"\bdrill\b", re.I)),
    ("julian_jacket", re.compile(r"\b(jacket|coat|pocket)\b", re.I)),
    ("crate", re.compile(r"\b(crate|tablecloth|the table|lid)\b|\bthe box\b", re.I)),
    ("boxes", re.compile(r"\bboxes\b|\bkitchen box\b", re.I)),
    ("takeaway", re.compile(r"\b(takeaway|food|noodles|dinner|plate)\b", re.I)),
    ("wine", re.compile(r"\b(wine|glass|bottle|drink)\b", re.I)),
    ("photo", re.compile(r"\b(photo|picture|photograph)\b", re.I)),
    ("window", re.compile(r"\bwindow\b", re.I)),
    ("car", re.compile(r"\b(car|hatchback|street)\b", re.I)),
    ("kitchen_island", re.compile(r"\b(island|counter|worktop)\b", re.I)),
    ("kitchen_floor", re.compile(r"\b(floor|tiles)\b", re.I)),
    ("trash_bag", re.compile(r"\b(trash|rubbish|garbage|bin bag|bin)\b", re.I)),
    ("bedroom_door", re.compile(r"\bbedroom\b", re.I)),
    ("tickets", re.compile(r"\b(tickets?|boarding pass\w*|passports?)\b", re.I)),
    ("movers_sign", re.compile(r"\bsign\b", re.I)),
    ("police", re.compile(r"\b(police|cops|911|999|emergency)\b", re.I)),
    ("nora", re.compile(r"\bnora\b", re.I)),
    ("leo", re.compile(r"\bleo\b", re.I)),
    ("julian", re.compile(r"\bjulian\b", re.I)),
    ("mia", re.compile(r"\bmia\b", re.I)),
    ("phone", re.compile(r"\bphone\b", re.I)),
]

PEOPLE = {"julian", "mia", "nora", "leo", "police"}
#: verbs that only make sense on a person
PERSON_VERBS = {"hug", "hit", "push", "grab"}
#: verbs that use up the turn's one object action (interaction-design.md §4.4); looking is free
OBJECT_VERBS = {"knock", "sit", "place", "open", "take", "eat", "drink", "pour", "toast", "search", "touch", "hit", "push", "grab"}
MOVE_VERBS = {"go_to", "leave", "take_aside"}

# --------------------------------------------------------------------------- discourse acts
ACTS: list[tuple[str, re.Pattern[str]]] = [
    ("threaten_to_tell", re.compile(
        r"\b(call|calling|tell|telling|go(ing)? to)\b.{0,20}\b(police|cops|nora)\b|\bi'?m (going to|gonna) tell\b|\bturn (you|them) in\b", re.I)),
    ("promise_silence", re.compile(
        r"\b(won'?t|will not|never) (tell|say)\b|\bkeep (it|this) (quiet|between us|secret)\b|\byour secret\b|"
        r"\bnot a word\b|\bi didn'?t see anything\b|\bmy lips are sealed\b", re.I)),
    ("accuse", re.compile(
        r"\b(you|julian|mia|he|she|they)\b.{0,30}\b(killed|hurt|murdered|did (something|this) to|did it|are hiding|is hiding|are lying|is lying|lied)\b", re.I)),
    ("mention_voicemail", re.compile(r"\bvoicemail\b|\b(he|leo) (called|rang) me\b|\bmissed calls?\b|\bleft (me )?a message\b", re.I)),
    ("mention_car", re.compile(
        r"\b(leo'?s|his|yellow|that) (car|hatchback)\b|\bcar\b.{0,30}\b(downstairs|outside|street|parked|curb)\b", re.I)),
    ("leave", re.compile(
        r"\b(i should (go|get going|head off)|i'?m (leaving|off|going home)|i have to go|good ?night|i'?ll head out|i need to go)\b", re.I)),
    ("comfort", re.compile(
        r"\b(it'?s (ok|okay|alright|all right)|you'?re (ok|okay|safe)|are you (ok|okay|alright|all right)|i'?m here|"
        r"don'?t worry|it'?ll be (ok|okay|fine)|take your time|breathe|i'?m sorry you)\b", re.I)),
    ("refuse", re.compile(r"^\s*(no|nope|nah)\b|\bno thanks\b|\bi('?d| would) rather not\b|\bi (can'?t|won'?t) do (that|this|it)\b|\bnot happening\b", re.I)),
    ("disagree", re.compile(
        r"\b(that'?s not (true|right|what happened)|i don'?t (think so|believe (you|that|him|her))|you'?re (wrong|lying)|"
        r"that doesn'?t add up|i doubt it)\b", re.I)),
    ("agree", re.compile(
        r"^\s*(yes|yeah|yep|sure|of course|okay|ok|right|absolutely|definitely|fair enough)\b|\b(you'?re right|i agree|i believe you|"
        r"he'?s right|she'?s right|deal)\b", re.I)),
    ("criticize", re.compile(r"\b(liar|ridiculous|pathetic|selfish|stop (it|lying)|you always|grow up|cruel)\b", re.I)),
    ("provoke", re.compile(
        r"\b(what are you hiding|admit it|something'?s (off|wrong)( here| with you)?|stop pretending|what'?s really going on)\b", re.I)),
    ("thank", re.compile(r"\bthank(s| you)\b", re.I)),
    ("apologize", re.compile(r"\b(sorry|apologi[sz]e)\b", re.I)),
    ("greet", re.compile(r"^\s*(hi|hello|hey|good evening)\b", re.I)),
    ("praise", re.compile(
        r"\b(looks|smells|tastes|sounds) (great|good|amazing|delicious|lovely)\b|\b(beautiful|gorgeous|nice place|well done|great idea|love this)\b", re.I)),
    ("confide", re.compile(r"\b(between (you and me|us)|can i tell you something|i have to tell you|i need to tell you|confession)\b", re.I)),
    ("joke", re.compile(r"\b(haha|lol|just kidding|joking)\b", re.I)),
]

ASK_ACTS: list[tuple[str, re.Pattern[str]]] = [
    ("ask_about_leo", re.compile(r"\bleo\b", re.I)),
    ("ask_about_crate", re.compile(r"\b(crate|box)\b", re.I)),
    ("ask_about_afternoon", re.compile(r"\b(afternoon|today|earlier|this morning|what happened)\b", re.I)),
    ("ask_about_move", re.compile(r"\b(move|moving|emigrat\w*|australia|new life|leaving|flight|why go)\b", re.I)),
]

TOPICS: list[tuple[str, re.Pattern[str]]] = [
    ("crate", re.compile(r"\b(crate|box|tablecloth)\b", re.I)),
    ("leo", re.compile(r"\bleo\b|\b(his|leo'?s|yellow) (car|hatchback)\b|\bvoicemail\b", re.I)),
    ("money", re.compile(r"\b(money|studio|cash|pay|afford|tickets?|savings|debt|share)\b", re.I)),
    ("afternoon", re.compile(r"\b(afternoon|today|earlier|this morning|what happened)\b", re.I)),
    ("marriage", re.compile(r"\b(marriage|married|you two|husband|wife|together|fight|argue|arguing)\b", re.I)),
    ("college", re.compile(r"\b(college|campus|uni|university|old days|remember when|back then|photo)\b", re.I)),
]

CLAIMS: list[tuple[str, re.Pattern[str]]] = [
    ("car_downstairs", re.compile(r"\b(leo'?s|his|yellow) (car|hatchback)\b|\bcar\b.{0,30}\b(downstairs|outside|street|parked|curb)\b", re.I)),
    ("missed_call", re.compile(r"\bvoicemail\b|\b(he|leo) (called|rang) me\b|\bmissed calls?\b", re.I)),
    ("leo_was_here", re.compile(r"\b(leo|he) (was|came|has been|'?s been) (here|by|over)\b|\bhe came (by|over|here)\b", re.I)),
    ("leo_dead", re.compile(r"\b(dead|killed|murdered|died)\b", re.I)),
    ("body_in_crate", re.compile(r"\b(in|inside) (the|that|this) (crate|box)\b", re.I)),
    ("embezzlement", re.compile(r"\b(studio money|stole|embezzl\w*|took the money)\b", re.I)),
    ("mia_called_leo", re.compile(r"\b(mia|you) called (him|leo)\b", re.I)),
    ("leo_wanted_money", re.compile(r"\b(wanted|came for|asking for|asked for) (his |the )?(money|share|cut)\b", re.I)),
    ("who_struck", re.compile(r"\b(hit him|the bottle)\b", re.I)),
    ("nora_pushed_leo", re.compile(r"\bnora (sent|pushed|told) him\b", re.I)),
]

_NORA_TRUTH = re.compile(
    r"\bhe('?s| is| was) here\b|\b(he|leo) (came|was) (here|by|over)\b|\bcome up\b|\bsomething'?s (wrong|happened)\b|"
    r"\b(dead|killed|crate|in the box|his phone is here|his car)\b", re.I)
_NORA_LIE = re.compile(
    r"\b(haven'?t|have not|didn'?t|did not|never) (seen|heard|come|came|show(ed)?|turn(ed)? up)\b|\bhe'?s not here\b|"
    r"\bnot here\b|\bno idea\b|\bhe flaked\b|\bhe never (came|showed)\b|\bdon'?t know where\b|\bno\b", re.I)

_EXPRESSION_ONLY = re.compile(
    r"^\s*(i\s+)?(smile|smiles|frown|frowns|stare|stares|glare|sigh|sighs|nod|nods|shrug|shrugs|grin|laugh|wince|blush|"
    r"raise an eyebrow|narrow my eyes|swallow|bite my lip|look away|go quiet)\b", re.I)
_QUOTE = re.compile(r"\"([^\"]+)\"|“([^”]+)”|「([^」]+)」|'([^']{2,}?)'(?=\s|$|[.,!?])")
_CJK = re.compile(r"[一-鿿]")


def _clean(s: str | None) -> str:
    return (s or "").strip()


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def _clauses(text: str) -> list[str]:
    parts = re.split(r",\s*(?:and\s+|then\s+)?|\band then\b|\bthen\b|\band\b|;", text, flags=re.I)
    return [p.strip() for p in parts if p and p.strip()]


class RuleEncoder:
    """Stateless; `objects` maps object name -> {topic, where} from data/interactions.yaml."""

    def __init__(self, objects: dict[str, dict[str, Any]] | None = None):
        self.objects = objects or {}

    # ------------------------------------------------------------------ entry point
    def encode(self, turn_input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        channels = self.segment(turn_input)
        present = [p for p in context.get("present") or [] if p in NPCS]
        on_call = bool(context.get("on_call_with_nora"))
        addressee = channels.get("addressee") or self.guess_addressee(channels, present, on_call)
        channels["addressee"] = addressee
        raw_text = turn_input.get("text") if turn_input.get("mode") == "single" else None
        validity, rewrite = self.validity(channels, raw_text)
        units = self.units(channels, context)
        speech = channels.get("speech", "")
        claims = sorted({fact for fact, rx in CLAIMS if rx.search(speech)})
        nora_answer = self.nora_answer(channels, units, addressee)
        acts = [u["act"] for u in units]
        suspicion = min(3.0, 0.6 * len(claims) + sum(0.5 for a in acts if a.startswith(("ask_about", "mention"))) +
                        sum(1.0 for a in acts if a.startswith("accuse") or a == "threaten_to_tell"))
        known = [a for a in acts if a not in ("explain", "ask", "observe", "silence")]
        return {
            "channels": channels,
            "translated": False,
            "validity": validity,
            "rewrite": rewrite,
            "units": units,
            "suspicion": round(suspicion, 2),
            "claims": claims,
            "coverage": 0.9 if known or any(u["action"] for u in units) or not units else 0.6,
            "nora_answer": nora_answer,
            "side_answer": None,  # the rule path leaves side questions to the act rules (beats/runner.side_answer)
        }

    # ------------------------------------------------------------------ segmentation
    def segment(self, turn_input: dict[str, Any]) -> dict[str, Any]:
        """Channels from a single text box (quotes are speech) or the filled-in channels as they are."""
        if turn_input.get("mode") != "single":
            ch = dict(turn_input.get("channels") or {})
            return {
                "speech": _clean(ch.get("speech")),
                "action": _clean(ch.get("action")),
                "expression": _clean(ch.get("expression")),
                "addressee": ch.get("addressee"),
            }
        text = _clean(turn_input.get("text"))
        speech_parts = ["".join(g for g in m.groups() if g) for m in _QUOTE.finditer(text)]
        rest = _QUOTE.sub(" ", text).strip(" ,.;:")
        rest = re.sub(r"\s{2,}", " ", rest).strip()
        rest = re.sub(r"\*([^*]+)\*", r"\1", rest).strip()
        if not speech_parts and rest and not self._looks_like_action(rest):
            speech_parts, rest = [rest], ""
        action, expression = "", ""
        if rest and speech_parts and not self._looks_like_action(rest):
            speech_parts.insert(0, rest)  # 'Hi Mia! "Good to see you."': the unquoted greeting is speech too
            rest = ""
        if rest:
            if _EXPRESSION_ONLY.search(rest) and not self._find_verb(rest):
                expression = rest
            else:
                action = rest
        speech = " ".join(p.strip() for p in speech_parts if p.strip())
        return {"speech": speech, "action": action, "expression": expression, "addressee": None}

    def _looks_like_action(self, text: str) -> bool:
        t = text.strip()
        if re.match(r"^(i|i'm|i am|my)\b", t, re.I):
            return True
        if _EXPRESSION_ONLY.search(t):
            return True
        first = t.split()[0].lower() if t.split() else ""
        return any(rx.match(first) for verb, rx in VERBS if verb not in ("text", "call")) and not t.endswith("?")

    @staticmethod
    def guess_addressee(channels: dict[str, Any], present: list[str], on_call: bool) -> str | None:
        speech = channels.get("speech") or ""
        if not speech and not channels.get("action"):
            return None
        text = f"{speech} {channels.get('action') or ''}"
        if re.search(r"\b(you two|both of you|guys|you both)\b", text, re.I):
            return "both"
        named = [n for n in NPCS if re.search(rf"\b{n}\b", speech, re.I)]
        if on_call:
            return "nora"
        # "Julian, ..." or "..., Mia?" addresses that person
        for n in named:
            if re.search(rf"^\s*{n}\b|,\s*{n}\s*[?.!]?\s*$", speech, re.I) and n in present:
                return n
        for n in NPCS:
            if re.search(rf"\b(to|at|ask|tell|turn to)\s+{n}\b", text, re.I) and n in present:
                return n
        hosts = [p for p in present if p in HOSTS]
        if "nora" in present and not hosts:
            return "nora"
        if len(hosts) == 1:
            return hosts[0]
        if speech and hosts:
            return "both"
        return None

    # ------------------------------------------------------------------ validity
    def validity(self, channels: dict[str, Any], raw_text: str | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
        everything = " ".join(filter(None, [raw_text, channels.get("speech"), channels.get("action"), channels.get("expression")]))
        # speech may say anything (interaction-design.md §4.3); the rest is the narrated part of the input
        narrated = " ".join(filter(None, [_QUOTE.sub(" ", raw_text) if raw_text else None, channels.get("action"), channels.get("expression")]))
        for label, rx in _VALIDITY_RULES:
            haystack = everything if label == "meta" else narrated
            m = rx.search(haystack)
            if not m:
                continue
            if label == "npc_action" and m.group(2).lower() in ("is", "was", "has", "does", "looks", "seems"):
                continue
            label = "stride" if label == "stride_time" else label
            span = m.group(0).strip(" .;,")
            return self._reject(label, span, channels, m)
        stride = self._stride_span(channels.get("action") or "")
        if stride:
            return self._reject("stride", stride, channels, None)
        return {"label": "ok", "span": None, "message": None}, None

    def _reject(self, label: str, span: str, channels: dict[str, Any], m: re.Match[str] | None):
        msg = VALIDITY_MESSAGES[label].format(span=span)
        return {"label": label, "span": span, "message": msg}, self._rewrite(label, span, channels, m)

    def _stride_span(self, action: str) -> str | None:
        moves = objs = 0
        for clause in _clauses(action):
            verb = self._find_verb(clause)
            if verb in MOVE_VERBS and self._room_of(clause):
                moves += 1
            elif verb in OBJECT_VERBS and self._find_target(clause):
                objs += 1
        if moves > 1 or objs > 1 or re.search(r"\b(come|came|go|went|get|got) back\b", action, re.I) and (moves or objs):
            return action
        return None

    def _rewrite(self, label: str, span: str, channels: dict[str, Any], m: re.Match[str] | None) -> dict[str, Any] | None:
        addressee = channels.get("addressee")
        if label in ("absurd", "out_of_scope", "meta"):
            return None
        if label == "npc_action":
            who = m.group(1).capitalize() if m else "them"
            speech = channels.get("speech", "")
            if span.lower() in speech.lower():
                speech = ""  # an unquoted single box went to speech; the offending text goes with the rewrite
            return {"speech": speech, "action": "", "expression": f"I watch {who}, waiting.", "addressee": who.lower()}
        if label == "npc_speech":
            who = m.group(1).capitalize() if m else "them"
            return {"speech": f"{who}, just tell me.", "action": "", "expression": "", "addressee": who.lower()}
        action = channels.get("action") or ""
        if label == "outcome":
            cut = re.split(r"\band (see|find|discover)\b|,?\s*\bwhich\b", action, maxsplit=1, flags=re.I)[0]
            cut = re.sub(r"\b(easily|successfully|finally)\s*", "", cut, flags=re.I)
            cut = re.sub(r"\b(manage|managed) to\s+", "", cut, flags=re.I).strip(" ,.")
            return {**channels, "action": f"I try to {cut[2:]}" if cut.lower().startswith("i ") else (cut or "I try."), "addressee": addressee}
        if label == "perception":
            fixed = re.sub(r"\bi (see|saw|notice|noticed|spot|spotted|realize|realise|sense)\b", "I look at", action, flags=re.I)
            fixed = re.sub(r"\bi (smell|smelled)\b", "I sniff at", fixed, flags=re.I)
            fixed = re.sub(r"\bi (hear|heard)\b", "I listen to", fixed, flags=re.I)
            expr = channels.get("expression") or ""
            return {**channels, "action": fixed, "expression": expr, "addressee": addressee}
        if label == "invention":
            return {**channels, "action": "I look around.", "addressee": addressee}
        if label == "stride":
            first = _clauses(action)[0] if action else ""
            first = re.split(r"\b(wait|waited|sit|sat|stay|stayed)\b.{0,15}\b(an hour|hours|all night|until morning|for ages)\b", first, flags=re.I)[0]
            return {**channels, "action": first.strip(" ,.") or "I wait.", "addressee": addressee}
        return None

    # ------------------------------------------------------------------ units
    def units(self, channels: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
        speech, action, expression = channels.get("speech", ""), channels.get("action", ""), channels.get("expression", "")
        addressee = channels.get("addressee")
        if not (speech or action or expression):
            return [{"channel": "speech", "text": "", "act": "silence", "addressee": None, "topics": [], "action": None, "implausible": False}]
        units: list[dict[str, Any]] = []
        for sentence in _sentences(speech):
            units.append({
                "channel": "speech", "text": sentence, "act": self.speech_act(sentence, addressee),
                "addressee": addressee, "topics": self.topics(sentence), "action": None, "implausible": False,
            })
        if action:
            parsed = self.parse_action(action, context, speech)
            topics = self.topics(action)
            if parsed and (t := (self.objects.get(parsed["target"]) or {}).get("topic")) and t not in topics:
                topics.append(t)
            units.append({
                "channel": "action", "text": action, "act": self.action_act(parsed, action, addressee),
                "addressee": addressee, "topics": topics, "action": parsed,
                "implausible": parsed is None and bool(self._find_verb(action)) and not _EXPRESSION_ONLY.search(action),
            })
        if expression:
            units.append({
                "channel": "expression", "text": expression, "act": "observe", "addressee": addressee,
                "topics": self.topics(expression), "action": None, "implausible": False,
            })
        return units

    @staticmethod
    def speech_act(sentence: str, addressee: str | None) -> str:
        for act, rx in ACTS:
            if not rx.search(sentence):
                continue
            if act == "accuse":
                low = sentence.lower()
                if "julian" in low and "mia" not in low:
                    return "accuse_julian"
                if "mia" in low and "julian" not in low:
                    return "accuse_mia"
                if addressee in HOSTS:
                    return f"accuse_{addressee}"
                continue
            return act
        if "?" in sentence:
            for act, rx in ASK_ACTS:
                if rx.search(sentence):
                    return act
            return "ask"
        if re.search(r"\bwhat happened\b", sentence, re.I):
            return "ask_about_afternoon"
        return "explain"

    @staticmethod
    def action_act(parsed: dict[str, Any] | None, text: str, addressee: str | None) -> str:
        if parsed is None:
            return "observe"
        verb = parsed["verb"]
        if verb == "leave":
            return "leave"
        if verb == "hug":
            return "comfort"
        if verb in ("hit", "push", "grab"):
            return "provoke"
        if verb == "call" and parsed["target"] == "police":
            return "threaten_to_tell"
        if verb == "listen_voicemail":
            return "observe"
        return "observe"

    @staticmethod
    def topics(text: str) -> list[str]:
        return [t for t, rx in TOPICS if rx.search(text or "")]

    # ------------------------------------------------------------------ action parsing
    @staticmethod
    def _find_verb(text: str) -> str | None:
        for verb, rx in VERBS:
            if rx.search(text):
                if verb == "go_to" and not RuleEncoder._room_of(text):
                    continue
                return verb
        return None

    @staticmethod
    def _room_of(text: str) -> str | None:
        for room, rx in ROOM_WORDS:
            if rx.search(text):
                return room
        return None

    @staticmethod
    def _find_target(text: str, allowed: set[str] | None = None) -> str | None:
        for target, rx in TARGETS:
            if (allowed is None or target in allowed) and rx.search(text):
                return target
        return None

    def parse_action(self, text: str, context: dict[str, Any], speech: str = "") -> dict[str, Any] | None:
        """The first (verb, target[, arg]) the action text names, mapped to the closed action table."""
        first = _clauses(text)[0] if _clauses(text) else text
        verb = self._find_verb(first) or self._find_verb(text)
        if verb is None:
            return None
        room = context.get("player_room")
        arg: str | None = None
        if verb == "go_to":
            target = self._room_of(text)
            if target is None:
                return None
        elif verb == "leave":
            target = "front_door"
        elif verb == "take_aside":
            m = re.search(r"\b(julian|mia)\b", text, re.I)
            target = m.group(1).lower() if m else None
            arg = self._room_of(text) or ("balcony" if target == "julian" else "kitchen")
            if target is None:
                return None
        elif verb in ("answer_call", "decline_call"):
            target = "nora"
        elif verb == "listen_voicemail":
            target = "phone"
        elif verb == "give_phone":
            target = "phone"
            m = re.search(r"\b(julian|mia|nora)\b", text, re.I)
            arg = m.group(1).lower() if m else None
        elif verb == "text":
            target = "nora"
            arg = self._message_body(text) or speech or None
        elif verb == "call":
            target = self._find_target(text, {"police", "nora", "leo"})
            if target is None:
                return None
        elif verb == "search":
            target = "julian_jacket"
        elif verb == "look_out":
            target = "car" if room == "balcony" else "window"
        elif verb in PERSON_VERBS:
            target = self._find_target(text, {"julian", "mia", "nora"})
            if target is None:
                if verb == "grab":
                    verb = "take"
                    target = self._find_target(text)
                else:
                    return None
        else:
            # "open the crate with the screwdriver": the tool is the means, not the target
            bare = text if verb == "take" else re.sub(r"\bwith (the|a|my|his|her) [\w ]+", "", text, flags=re.I)
            target = self._find_target(bare)
            if target is None and verb in ("touch", "examine"):
                target = self._find_target(text, {"julian", "mia", "nora"})
            if target is None:
                return None
            if verb == "take" and target in ("julian", "mia", "nora"):
                verb = "grab"
        out: dict[str, Any] = {"verb": verb, "target": target}
        if arg is not None:
            out["arg"] = arg
        return out

    @staticmethod
    def _message_body(text: str) -> str | None:
        m = _QUOTE.search(text)
        if m:
            return "".join(g for g in m.groups() if g)
        m = re.search(r"(?::|\bsaying\b|\bthat\b)\s*(.+)$", text, re.I)
        return m.group(1).strip() if m else None

    # ------------------------------------------------------------------ Nora
    @staticmethod
    def nora_answer(channels: dict[str, Any], units: list[dict[str, Any]], addressee: str | None) -> str | None:
        to_nora = addressee == "nora"
        texts = [channels.get("speech") or ""] if to_nora else []
        for u in units:
            a = u.get("action") or {}
            if a.get("target") == "nora" and a.get("verb") == "text":
                to_nora = True
                texts.append(a.get("arg") or "")
        if not to_nora:
            return None
        text = " ".join(texts)
        if _NORA_TRUTH.search(text):
            return "truth"
        if _NORA_LIE.search(text):
            return "lie"
        return "none"


def is_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))
