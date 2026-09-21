# CS 457 Project Statement of Work (SOW) & Protocol Specification Template

**Student Name:** April Harmon  
**Date:** 2026-09-20
**Course:** CS 457 - Computer Networks  
**Target Server Domain:** `server.harmon.edu`  

---

## 1. Game Selection & Scope (Sprint 0)

> Planning is going to be an iterative process through the sprints so you don't have to have all the details now. Focus on big overview concepts. You will be updating the SOW as we plan.
> You have a lot of freedom to choose a game. There are a couple caveats.  

> - It must run in the console. The lab nodes won't be able to handle extensive graphics.
> - It has to be self-contained. You can use a internet-connector to download you code, but because the architecture must run 5 nodes you won't be able to run 
> - You are encouraged to use python, but I'm not going to make it a strict requirement. The instructor and TA's ability to help with C or Rust, etc will be diminished in other languages.

### 1.1 Game Overview
- **Chosen Game:** Blackjack
- **Player Capacity:** 2 Players (Simulated via 2 CML Client nodes)
- **Game Summary:** Blackjack is a game of luck and getting to 21

### 1.2 Core Game Rules & Win/Draw Conditions
- **Turn Mechanics:** 

  Player roles are decided by the following:
  - The Server will occupy the role of the dealer
  - Each Client will occupy the role of the player

  The Dealer (Server Side):
  - Set-Up
    - The server will create a game and wait for players to join.
    - After players have joined and all players have placed their bets the game will start and the dealer will draw 2 cards per player from a couple of shuffled decks. These cards are distributed     face-up to each of the players that have placed a bet. Afterward the dealer will draw one card know as the "Up" card which is placed face-up and one card known as the "Hole" card which is       placed face-down.
    - If the "Up" card is a ten-valued card like a 10, Jack, Queen, or King, the dealer will peek at the "Hole" card to check if a natural blackjack has occurred.
    - If the "Up" card is an Ace the dealer will offer insurance and after it's been accepted or declined by each player the dealer will peek at the "Hole" card to check if a natural blackjack has occurred and pay out accordingly to insurance.
    
  - During Play
    - After the set-up the dealer will go around to each player that has made a bet and if requirements are met will ask if they would like to "Hit", "Stand", "Double Down", or "Split".
      
    - Hit
      - If the player asks to "Hit" the dealer will draw a new card from the shuffled decks, deal it to the player face-up, and move to the next player. A player can always have the option of hitting unless the player has previously chose "Double Down"
        
    - Stand
      - If the player asks to "Stand" the dealer will do nothing and move to the next player. A player can always have the option of standing unless the player has previously chose "Double Down"
        
    - Double Down
      - If the player has at least an equal amount of money in their account to their initial bet the dealer will give the player a third option to "Double Down" the dealer will "Hit" the player and then the player will automatically "Stand" for the rest of the current hand. After the dealer moves to the next player.
    
    - Split
      - If a player is dealt a pair of cards at the start of the hand and has at least an equal amount of money in their account to their initial bet, the dealer will give the player a forth option to "Split" during the first round. If a player chooses to "Split" the dealer will split the pair into two new hands and deal a new card for each hand so the player has two hands of two cards each. The dealer will also have the player put an equal bet on the newly created hand. After the dealer moves to the next player.
    - After each player has either chose to "Stand" or has lost via the win/lose conditions the dealer will flip the "Hole" card and reveal it to the players.
    - If the dealer's total value of their cards is less than 17 the dealer must "Hit" until the total value of their cards is greater than or equal to 17. After the this condition is met the dealer will check to see what win/lose condition has been met for each player.

  The Player (Client Side):
  - Set-Up
    - Each Player will receive a player number based off the order the clients join in when the server is first initialized. If a client loses connection to the server the client will keep the player number it had before disconnecting unless the server restarts in the meantime.
    - After connecting to the server and joining the game each player will select an amount of money to bet. Placing the bet will tell the server that player is ready to play. The players will then be dealt cards and given options by the dealer.
    - If the dealer offers insurance each player is allowed to make an additional side bet for up to 50% of their initial bet on whether the dealer has a natural blackjack.
    
  - During Play
    - Each round when it's their turn a Player can choose to either "Hit", "Stand", "Double Down", or "Split" if requirements for each option are met.

- **Victory Condition:** 
    
    Win:
  - If the player has a higher total than the dealer at the end of the round, that player wins.
  - If the dealer's total goes over a total of 21, all players that didn't also go over win.
  - Win without Blackjack is paid out at a 1:1 ratio
  - Win with Blackjack is paid out at a 3:2 ratio
  - If a player has insurance and the dealer has a natural blackjack the bet is paid out at a 2:1 ratio

   Lose:
  - If the dealer has a higher total than the player at the end of the round, that player loses.
  - If the player goes over a total of 21, that player loses.
  - If player loses bet money is lost to the dealer

- **Draw/Tie Condition:**
  - If the dealer and the player has the same total value at the end the game is tied and the bet is returned to the player.

---

## 2. Application-Layer Messaging Protocol Blueprint (Sprint 1 Deliverable)

### 2.1 Message Transport & Serialization Format
- **Transport Protocol:** TCP
- **Serialization Format:** [JSON / Fixed-Header Binary / Delimited Text]
- **Framing Mechanism:** [e.g., Newline-delimited (`\n`) JSON payloads OR 4-byte big-endian length prefix]

### 2.2 Message Schema Definitions

#### Message Types:
1. `CONNECT` (Client -> Server): Request to join the game room.
2. `LOBBY_WAIT` (Server -> Client): Notification that server is waiting for Player 2.
3. `GAME_START` (Server -> Clients): Game initiated, assigns roles (e.g. Player X vs Player O).
4. `MOVE` (Client -> Server): Player action (e.g., cell coordinates or answer choice).
5. `STATE_UPDATE` (Server -> Clients): Broadcast current game board / state and active player turn.
6. `GAME_OVER` (Server -> Clients): Victory / Draw notification with final scores.
7. `ERROR` (Server -> Client): Invalid move or malformed packet error.

#### Example JSON Protocol Schema:
```json
{
  "msg_type": "MOVE",
  "player_id": "Player_1",
  "payload": {
    "row": 0,
    "col": 2
  },
  "timestamp": 1727000000
}
```

---

### 2.3 Game State Machine (FSM) Design (Sprint 1 Deliverable)
- **State Transitions:** Detail state flow: `INIT` -> `WAITING_FOR_PLAYERS` -> `PLAYER_TURN` -> `EVALUATE_MOVE` -> `CHECK_WIN_DRAW` -> `GAME_OVER` -> `CLEANUP`.

---

## 3. Game Behavior & Server Concurrency Architecture (Sprint 2 Deliverable)

### 3.1 Server Concurrency Strategy
- **Architecture Choice:** [Multi-Threading (`threading.Thread`) OR Non-blocking I/O multiplexing (`select.select` / `selectors`)]
- **Synchronization Logic:** Explain how shared game state and client list are thread-safe (e.g. `threading.Lock`) to prevent race conditions during turn processing.

### 3.2 State & Score Synchronization Across Clients
- **Turn Enforcement:** Detail how the server validates active player ID before processing moves and broadcasts updated turn notifications to all clients.
- **Score & Board Synchronization:** Describe how state broadcasts keep client screens synchronized in real time.

---

## 4. Coding & AI Implementation Plan (Sprint 3)

- **Permitted AI Tools:** [e.g., GitHub Copilot, ChatGPT, Claude]
- **AI Prompting & Constraint Strategy:** Explain how you will constrain AI models to generate code (in Python or your chosen language) that adheres strictly to the protocol blueprint and FSM designed in Sprints 1 & 2.
- **Implementation Risk Management:** Detail your plan to leverage past programming experience and manage time to ensure code completion on schedule.

---

## 5. CML Multi-Subnet Topology & Wireshark Deployment Plan (Sprint 4 & 5 Deliverable)

> For now you can use the topology below. We may update this when we get to defining subnets.

### 5.1 Subnet & Router Design
- **Subnet A (Client 1):** `192.168.10.0/24` (Interface `Gi0/1` on Router R1)
- **Subnet B (Client 2):** `192.168.11.0/24` (Interface `Gi0/2` on Router R1)
- **Subnet C (Game Server):** `192.168.20.0/24` (Interface `Gi0/1` on Router R2)
- **Router Backbone:** `10.0.0.0/30` (Interface `Gi0/0` on R1 <-> `Gi0/0` on R2)

### 5.2 DHCP Pools & DNS Configuration Plan
- **Router R1 DHCP Pool 1 (`CLIENT1_POOL`):** Leases `192.168.10.10` - `192.168.10.50`, gateway `192.168.10.1`, DNS `10.0.0.2`.
- **Router R1 DHCP Pool 2 (`CLIENT2_POOL`):** Leases `192.168.11.10` - `192.168.11.50`, gateway `192.168.11.1`, DNS `10.0.0.2`.
- **Router R2 Authoritative DNS:** Configured with `ip dns server` and static host mapping `server.[yourlastname].edu` -> `192.168.20.100`.

### 5.3 Deployment Strategy & Wireshark Trace Capture
- **CML Deployment Strategy:** Deploy `server.py` onto Subnet C node (`192.168.20.100`) behind Router R2, and `client.py` onto Subnet A and Subnet B nodes behind Router R1.
- **Cisco Infrastructure Configuration:** Router R1 DHCP pools (`CLIENT1_POOL`, `CLIENT2_POOL`) and Router R2 authoritative DNS (`ip host server.[lastname].edu 192.168.20.100`).
- **Wireshark Trace Capture Plan:** Capture DHCP DORA exchange (`dhcp_negotiation.pcap`) and DNS query/response resolution (`dns_lookup.pcap`).
