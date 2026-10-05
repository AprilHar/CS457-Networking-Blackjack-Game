## 2. Application-Layer Messaging Protocol Blueprint (Sprint 1 Deliverable)

### 2.1 Message Transport & Serialization Format
- **Transport Protocol:** TCP
- **Serialization Format:** [JSON]
- **Framing Mechanism:** [Newline-delimited (`\n`) JSON payloads]

### 2.2 Message Schema Definitions

#### Default JSON Protocol Schema:
  ```json
      {
        "msg_type": "string",
        "player_id": "string",
        "timestamp": 0,
        "payload": {}
      }
  ```

#### Message Types:
1. `CONNECT` (Client -> Server): Request to join the game table.
```json
      {
        "msg_type": "CONNECT",
        "player_id": "gambler_1",
        "timestamp": 1728086400,
        "payload": {
            "player_name": "Joker",
            "balance": 500
        }
      }
```
      
2. `LOBBY_WAIT` (Server -> Client): Notification that server is waiting for Player 2.
```json
      {
        "msg_type": "LOBBY_WAIT",
        "player_id": "dealer",
        "timestamp": 1728086401,
        "payload": {
            "message": "Waiting for Player 2 to join...",
            "current_players": 1,
            "required_players": 2,
            "assigned_id": "gambler_1"
        }
      }
  ```

3. `READY` (Client -> Server): Tells the Server that player has made bet, thus is ready.
```json
      {
        "msg_type": "READY",
        "player_id": "gambler_1",
        "timestamp": 1728086405,
        "payload": {
            "bet_amount": 25,
            "ready_status": true
        }
      }
  ```
     
4. `GAME_START` (Server -> Clients): Blackjack Table is initiated.
```json
      {
        "msg_type": "GAME_START",
        "player_id": "dealer",
        "timestamp": 1728086410,
        "payload": {
            "dealer_up_card": {
            "suit": "HEARTS",
            "rank": "10"
            },
            "players": [
            {
                "player_id": "gambler_1",
                "bet": 25,
                "hand": [
                { "suit": "SPADES", "rank": "A" },
                { "suit": "CLUBS", "rank": "K" }
                ]
            },
            {
                "player_id": "gambler_2",
                "bet": 50,
                "hand": [
                { "suit": "DIAMONDS", "rank": "8" },
                { "suit": "HEARTS", "rank": "7" }
                ]
            }
            ],
            "current_turn": "gambler_1"
        }
      }
  ```
      
5. `MOVE` (Client -> Server): Player action (e.g., hit, stand, double, split).
```json
      {
        "msg_type": "MOVE",
        "player_id": "gambler_1",
        "timestamp": 1728086415,
        "payload": {
          "action": "HIT",
          "hand_index": 0
        }
      }
  ```
     
6. `STATE_UPDATE` (Server -> Clients): Broadcast current board / state and active player turn.
```json
      {
        "msg_type": "STATE_UPDATE",
        "player_id": "dealer",
        "timestamp": 1728086416,
        "payload": {
          "last_action": {
            "player_id": "gambler_1",
            "action": "HIT",
            "card_dealt": {
              "suit": "SPADES",
              "rank": "5"
            }
          },
          "dealer": {
            "up_card": { "suit": "HEARTS", "rank": "10" },
            "score": 10
          },
          "players": [
            {
              "player_id": "gambler_1",
              "balance": 475,
              "hands": [
                {
                  "cards": [
                    { "suit": "SPADES", "rank": "A" },
                    { "suit": "CLUBS", "rank": "5" },
                    { "suit": "SPADES", "rank": "5" }
                  ],
                  "score": 21,
                  "bet": 25,
                  "status": "ACTIVE"
                }
              ]
            },
            {
              "player_id": "gambler_2",
              "balance": 450,
              "hands": [
                {
                  "cards": [
                    { "suit": "DIAMONDS", "rank": "8" },
                    { "suit": "HEARTS", "rank": "7" }
                  ],
                  "score": 15,
                  "bet": 50,
                  "status": "ACTIVE"
                }
              ]
            }
          ],
          "current_turn": "gambler_1"
        }
      }
  ```
      
7. `GAME_OVER` (Server -> Clients): Victory / Draw notification with final scores.
```json
      {
        "msg_type": "GAME_OVER",
        "player_id": "dealer",
        "timestamp": 1728086430,
        "payload": {
          "dealer_hand": {
            "cards": [
              { "suit": "HEARTS", "rank": "10" },
              { "suit": "DIAMONDS", "rank": "6" },
              { "suit": "CLUBS", "rank": "6" }
            ],
            "score": 22,
            "status": "BUSTED"
          },
          "results": [
            {
              "player_id": "gambler_1",
              "hand_index": 0,
              "player_score": 21,
              "outcome": "WIN",
              "payout": 50,
              "final_balance": 525
            },
            {
              "player_id": "gambler_2",
              "hand_index": 0,
              "player_score": 24,
              "outcome": "LOSS",
              "payout": 0,
              "final_balance": 450
            }
          ]
        }
      }
  ```
     
8. `ERROR` (Server -> Client): Invalid move or malformed packet error.
```json
      {
        "msg_type": "ERROR",
        "player_id": "dealer",
        "timestamp": 1728086432,
        "payload": {
          "error_code": "INVALID_MOVE",
          "message": "Double down is only permitted on the initial two cards."
        }
      }
  ```

9. `DISCONNECT` (Client -> Server): Client notifies server of intentional departure/quit.
```json
      {
        "msg_type": "DISCONNECT",
        "player_id": "gambler_2",
        "timestamp": 1728086450,
        "payload": {
          "reason": "USER_QUIT",
          "message": "Player left the table."
        }
      }
  ```
