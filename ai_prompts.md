# AI Prompts (Sprint 1 Deliverable)
This file contains standardized prompts and task instructions for AI assistants working in this repository.

---

## 1. System Prompt / Context Injection

Use this block to keep LLM focused while building the protocol:

```text
You are building a 2-player client-server Blackjack game.

CORE PROTOCOL REFERENCE:
- Check `protocol_blueprint.md` first: Before creating, modifying, or refactoring message structures, classes, or any logic. 
- Check `protocol_blueprint.md` first: to verify field names, types, and message structures.
- No Unilateral Schema Changes: Never in any way add, delete, modify the specifications listed in protocol_blueprint.md
- All network packets MUST strictly match the default JSON envelope:
  {
    "msg_type": "string",
    "player_id": "string",
    "timestamp": 0,
    "payload": {}
  }
- Valid msg_types: CONNECT, LOBBY_WAIT, READY, GAME_START, MOVE, STATE_UPDATE, GAME_OVER, ERROR, DISCONNECT.
- Sender IDs: "gambler_1", "gambler_2", "dealer".
- Allowed player actions: "HIT", "STAND", "DOUBLE", "SPLIT".

CODING STANDARDS:
- Handle TCP socket streaming properly: enforce framing/delimiters (e.g., newline `\n` or length-prefixed bytes) so JSON packets do not split or merge in the buffer.
- Never trust client inputs: validate balances, turns, card values, and game states strictly on the server.
- Write clean, modular code with descriptive error handling.
```

## 2. Error Checking

I plan to develope code based of unit testing and error checking when writing code using an LLM. This will ensure that no game breaking errors or bugs will occur in the development of the code and protocol.

## 3. Planning

As stated in lecture I will always have the LLM plan code out before implementing anything. Anything that is implemented will have been checked over by myself and tested before being put on a live branch.

