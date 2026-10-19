# Server Concurrency Strategy (Sprint 2 Deliverable)
## **Architecture Choice:** [Non-blocking I/O multiplexing (`select.select` / `selectors`)]
### Architecture Requirements for Blackjack Game
- Needs to be simple in regrads to implementation
- Players act only on thier turn and have to wait for the other player to play, therefor one action at a time is reasonable
- Players need to be able to easily and quickly be able to reconnect if a disconnect occurs
- Minimal resources are required per player since payloads don't handle large amounts of data
- Needs to maintain and easliy send the state of the game

### Why Selectors?
Selectors are the obvious choice for the network connected game of blackjack I am creating. Selectors have many more benifits over threads in this context. They are much less costly to tear down and rebuild for player disconnects/reconnects which is important since networks connections are usually run over unrealiable channels. Selectors are also better suited for sending small messages which is the type of messages that were outlined in protocol_blueprints.md file. They end up working better for keeping track of the game state and sending it since the processing would run on a single thread.

### Detailed Reasons
#### 1. Naturally Models Turn-Based Progression (One Action at a Time)
- In a multi-threaded design (threading.Thread), each client thread runs concurrently, requiring synchronization primitives like threading.Lock to block out-of-turn execution and prevent simultaneous state changes. A selectors event loop is single-threaded by design. It sequentially dequeues incoming I/O events, naturally processing one action at a time without race conditions or lock contention.
#### 2. Simpler State Management & Synchronization
- Because execution happens on a single thread, the server’s shared game state—the dealer's shoe, current turn, player hands, chip counts, and the Finite State Machine (FSM)—can be modified directly without locking mechanisms.
- Broadcasting STATE_UPDATE packets to both clients after a move is straightforward: the server serializes the updated state once and writes it directly to both client socket output buffers within the same execution step.
#### 3. Faster, Cleaner Disconnections & Reconnections
- With selectors, disconnecting a client requires only unregistering the socket from the selector loop (selector.unregister(sock)) and closing it. It offers lower teardown costs and simpler reconnect handling compared to threads.
- In a multi-threaded setup, disconnecting requires interrupting or terminating blocking recv() loops, joining worker threads, and cleaning up thread resources safely.
- When a player drops, their underlying table data (assigned player_id, hand, bets) remains intact in memory. When the client reconnects via a new socket, the selector registers the new file descriptor, re-associates it with the player's saved state, and resumes play.
#### 4. Minimal Resource Footprint for Lightweight Payloads
- The messaging protocol exchanges small, newline-delimited JSON envelopes (CONNECT, MOVE, STATE_UPDATE, etc.).
- Multi-threading allocates a dedicated thread stack (typically several megabytes per thread in virtual memory) and introduces OS-level context-switching overhead just to idle while waiting for tiny messages.
- Selectors monitor raw file descriptors directly at the kernel level, consuming minimal memory and CPU resources, making them better suited for tasks that only transfer small messages.

## **Synchronization Logic:** Explains how shared game state and client list are thread-safe (e.g. `threading.Lock`) to prevent race conditions during turn processing.
### In-Memory Score Storage Architecture
Because the server operates on a non-blocking I/O event loop using selectors, all game and score structures reside in memory within a single thread, eliminating mutex lock overhead.
#### Persistent Player Sessions & Leaderboard:
- Keys are tied to the canonical identifiers "gambler_1" and "gambler_2".   
- Stored attributes include player_name, current chip balance (e.g., initialized via CONNECT), placed bet amounts, active socket connection, and win/loss/tie statistics.
- These session balances persist across rounds and mid-game drops so reconnecting players retain their chips and identity.   
#### Round-Level Hand Scoring:
- Each player record maintains a dynamic hands list (supporting hand indices for splits).
- Each hand object contains the current card array (suit, rank), current evaluated numeric score, active bet, and hand status (ACTIVE, BUSTED, STAND)
- The dealer hand structure stores the dealer's hole card, up card, running card total, and bust status.
#### Calculation Engine:
- When resolving the round after the dealer completes draws to 17 or higher, the engine evaluates win conditions (e.g., standard 1:1 payout, 3:2 natural blackjack, or returned bets on ties/pushes).
- Payout calculations directly adjust the in-memory balance: final_balance = balance + payout

### Broadcast Logic Upon Round Completion
When the server's Finite State Machine transitions through DEALER_TURN -> ROUND_END -> CLEANUP, the server triggers a synchronized broadcast of the final score table to both clients using the standard GAME_OVER schema higlighted in the GAME_OVER sequence diagram.
### Broadcast Execution Workflow
#### Compilation of Final Results:
- The server compiles the revealed dealer hand and an array containing the outcome for both players into a single structured payload like the GAME_OVER message seen in the protocol_blueprint.md file.
#### Framing & Serialization:
- The server serializes the dictionary into JSON and appends the newline delimiter (\n) to conform with the TCP streaming protocol specifications.
#### Selector Outbound Dispatch:
- The single-threaded event loop writes the encoded bytes directly into each client's registered socket output buffer.
- If a socket cannot take the entire payload immediately, the selector marks the client for EVENT_WRITE to flush remaining bytes without blocking the main thread.
#### Client-Side Display Synchronization:
- Upon receiving and parsing the GAME_OVER frame, each client's console interface prints the dealer's final hand, compares both players' final scores, updates their displayed balance, and presents options for the next betting phase.

