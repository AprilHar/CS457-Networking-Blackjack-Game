# State & Score Synchronization Across Clients (Sprint 2 Deliverable)
## CONNECT & LOBBY_WAIT Sequence
```mermaid
sequenceDiagram
    autonumber
    actor Gambler1 as gambler_1
    participant Server as dealer (Server)
    actor Gambler2 as gambler_2

    Note over Gambler1,Server: Client 1 connects first
    Gambler1->>Server: CONNECT {"player_name": "Joker", "balance": 500}
    Server-->>Gambler1: LOBBY_WAIT {"assigned_id": "gambler_1", "current_players": 1, "required_players": 2}

    Note over Server,Gambler2: Client 2 connects
    Gambler2->>Server: CONNECT {"player_name": "Queen", "balance": 500}
    Server-->>Gambler2: LOBBY_WAIT {"assigned_id": "gambler_2", "current_players": 2, "required_players": 2}
```
## READY & GAME_START Sequence
```mermaid
sequenceDiagram
    autonumber
    actor Gambler1 as gambler_1
    participant Server as dealer (Server)
    actor Gambler2 as gambler_2

    Gambler1->>Server: READY {"bet_amount": 25, "ready_status": true}
    Note over Server: Server records Gambler 1 bet.<br/>Awaiting Gambler 2...
    Gambler2->>Server: READY {"bet_amount": 50, "ready_status": true}

    Note over Server: Both ready. Server deals 2 cards each<br/>+ 1 up card & 1 hole card to dealer.
    
    par Broadcast Table Setup
        Server->>Gambler1: GAME_START {"dealer_up_card": {"rank": "10"}, "current_turn": "gambler_1", ...}
    and
        Server->>Gambler2: GAME_START {"dealer_up_card": {"rank": "10"}, "current_turn": "gambler_1", ...}
    end
```
## MOVE & STATE_UPDATE Sequence
```mermaid
sequenceDiagram
    autonumber
    actor Gambler1 as gambler_1
    participant Server as dealer (Server)
    actor Gambler2 as gambler_2

    %% --- MOVE 1: HIT ---
    Gambler1->>Server: MOVE (action: "HIT", hand_index: 0)
    critical Valid Move? Can Hit? Gambler 1 Turn?
        Note over Server: Is Valid (gambler_1 turn)
        Note over Server: Check Game State<br/>(Card total ≤ 21? Can move again? Still turn?)
        par Broadcast State Update
            Server->>Gambler1: STATE_UPDATE (Cards: [A♥, 4♠, 5♦], total: 20, turn: gambler_1)
        and
            Server->>Gambler2: STATE_UPDATE (turn: gambler_1)
        end
    end

    %% --- MOVE 2: STAND ---
    Gambler1->>Server: MOVE (action: "STAND", hand_index: 0)
    critical Valid Move? Stand? Turn?
        Note over Server: Is Valid<br/>Switch Gamblers -> gambler_2
        Note over Server: Check Game State<br/>(Card total ≤ 21? Turn?)
        par Broadcast State Update
            Server->>Gambler1: STATE_UPDATE (Cards: [A♥, 4♠, 5♦], total: 20, turn: gambler_2)
        and
            Server->>Gambler2: STATE_UPDATE (turn: gambler_2)
        end
    end

    %% --- MOVE 3: INVALID DOUBLE ---
    Gambler2->>Server: MOVE (action: "DOUBLE", hand_index: 0)
    critical Is Valid? Double? Turn?
        Note over Server: Not Valid (Insufficient Balance / Rules Check)
        Server->>Gambler2: ERROR (msg: "Insufficient Balance to double")
    end
```
## GAME_OVER Sequence
```mermaid
sequenceDiagram
    autonumber
    actor Gambler1 as gambler_1
    participant Server as dealer (Server)
    actor Gambler2 as gambler_2

    Note over Server: All players done (STAND/BUST).<br/>Dealer reveals hole card & hits to 17+.
    Note over Server: Evaluate outcomes:<br/>Gambler 1: WIN (payout 50)<br/>Gambler 2: LOSS (bust)

    par Broadcast Final Results
        Server->>Gambler1: GAME_OVER {"results": [{"player_id": "gambler_1", "outcome": "WIN", "payout": 50}], "dealer_hand": {...}}
    and
        Server->>Gambler2: GAME_OVER {"results": [{"player_id": "gambler_2", "outcome": "LOSS", "payout": 0}], "dealer_hand": {...}}
    end
```
## DISCONNECT & RECONNECT Sequence
```mermaid
sequenceDiagram
    autonumber
    actor Gambler1 as gambler_1
    participant Server as dealer (Server)
    actor Gambler2 as gambler_2

    %% -------------------------------------------------
    %% 1. DISCONNECT PHASE
    %% -------------------------------------------------
    Note over Gambler2,Server: DISCONNECT PHASE
    Gambler2->>Server: DISCONNECT {"reason": "USER_QUIT", "message": "Player disconnected."}
    Note over Server: Server marks gambler_2 as disconnected.<br/>Retains player_id & active game state.
    
    Server->>Gambler1: LOBBY_WAIT {"message": "gambler_2 disconnected. Waiting for reconnection...", "current_players": 1, "required_players": 2}

    %% -------------------------------------------------
    %% 2. RECONNECTION PHASE
    %% -------------------------------------------------
    
    Note over Gambler2,Server: RECONNECTION PHASE
    Gambler2->>Server: CONNECT {"player_name": "Queen", "balance": 450}
    
    critical Match Reconnecting Client
        Note over Server: Server recognizes returning client.<br/>Re-associates session with "gambler_2".
        
        par Restore Game State to Both Players
            Server->>Gambler2: STATE_UPDATE {"dealer": {...}, "players": [...], "current_turn": "gambler_1"}
        and
            Server->>Gambler1: STATE_UPDATE {"dealer": {...}, "players": [...], "current_turn": "gambler_1"}
        end
    end
    
    Note over Gambler1,Gambler2: Gameplay resumes from the saved turn state.
```
