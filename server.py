"""
server.py — 2-Player Blackjack Dealer Server
CS 457 Networking — Sprint 2

Usage:
    python3 server.py -p <PORT>
    python3 server.py -h

Architecture:
    - Single-threaded selectors-based I/O multiplexing (no threads, no locks)
    - Finite State Machine (FSM) enforces legal game-state transitions
    - Newline-delimited (\n) JSON framing over TCP
    - All validation is server-side; client input is never trusted
"""

import argparse
import json
import random
import selectors
import socket
import sys
import time
from enum import Enum, auto


# ---------------------------------------------------------------------------
# FSM State Definitions
# ---------------------------------------------------------------------------

class ServerFSM(Enum):
    """All legal server FSM states per fsm_specification.md."""
    DISCONNECTED        = auto()
    WAITING_FOR_PLAYERS = auto()
    BETTING             = auto()
    DEALING             = auto()
    PLAYER_TURN         = auto()
    ALL_PLAYERS_DONE    = auto()
    DEALER_TURN         = auto()
    ROUND_END           = auto()
    CLEANUP             = auto()


# Valid FSM transitions: (current_state, event) -> next_state
# Events are plain strings describing what triggered the transition.
FSM_TRANSITIONS = {
    (ServerFSM.DISCONNECTED,        "player_connected"):   ServerFSM.WAITING_FOR_PLAYERS,
    (ServerFSM.WAITING_FOR_PLAYERS, "player_connected"):   ServerFSM.BETTING,
    (ServerFSM.WAITING_FOR_PLAYERS, "disconnect"):         ServerFSM.CLEANUP,
    (ServerFSM.BETTING,             "wagers_ready"):       ServerFSM.DEALING,
    (ServerFSM.BETTING,             "disconnect"):         ServerFSM.CLEANUP,
    (ServerFSM.DEALING,             "game_start"):         ServerFSM.PLAYER_TURN,
    (ServerFSM.DEALING,             "disconnect"):         ServerFSM.CLEANUP,
    (ServerFSM.PLAYER_TURN,         "hit_or_split"):       ServerFSM.PLAYER_TURN,
    (ServerFSM.PLAYER_TURN,         "turn_ends"):          ServerFSM.ALL_PLAYERS_DONE,
    (ServerFSM.PLAYER_TURN,         "disconnect"):         ServerFSM.CLEANUP,
    (ServerFSM.ALL_PLAYERS_DONE,    "next_player"):        ServerFSM.PLAYER_TURN,
    (ServerFSM.ALL_PLAYERS_DONE,    "all_done"):           ServerFSM.DEALER_TURN,
    (ServerFSM.DEALER_TURN,         "dealer_resolves"):    ServerFSM.ROUND_END,
    (ServerFSM.ROUND_END,           "game_over"):          ServerFSM.CLEANUP,
    (ServerFSM.CLEANUP,             "both_remain"):        ServerFSM.BETTING,
    (ServerFSM.CLEANUP,             "one_remains"):        ServerFSM.WAITING_FOR_PLAYERS,
    (ServerFSM.CLEANUP,             "none_remain"):        ServerFSM.DISCONNECTED,
}

# Card suits and ranks
SUITS = ["HEARTS", "DIAMONDS", "CLUBS", "SPADES"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]

# Suit symbols for display
SUIT_SYMBOLS = {"HEARTS": "♥", "DIAMONDS": "♦", "CLUBS": "♣", "SPADES": "♠"}

# Valid message types and player IDs per protocol_blueprint.md
VALID_MSG_TYPES = {
    "CONNECT", "LOBBY_WAIT", "READY", "GAME_START",
    "MOVE", "STATE_UPDATE", "GAME_OVER", "ERROR", "DISCONNECT"
}
VALID_PLAYER_IDS = {"gambler_1", "gambler_2", "dealer", "unknown"}
VALID_ACTIONS = {"HIT", "STAND", "DOUBLE", "SPLIT"}
PLAYER_IDS = ["gambler_1", "gambler_2"]

# Hand status constants
STATUS_ACTIVE  = "ACTIVE"
STATUS_STAND   = "STAND"
STATUS_BUSTED  = "BUSTED"
STATUS_BJ      = "BLACKJACK"


# ---------------------------------------------------------------------------
# Card & Deck Utilities
# ---------------------------------------------------------------------------

def build_deck():
    """
    Build and shuffle a standard 52-card deck.

    Returns:
        list[dict]: Shuffled list of {'suit': str, 'rank': str} dicts.
    """
    deck = [{"suit": s, "rank": r} for s in SUITS for r in RANKS]
    random.shuffle(deck)
    return deck


def card_label(card):
    """Return a human-readable card label like 'A♥' or '10♠'."""
    return f"{card['rank']}{SUIT_SYMBOLS.get(card['suit'], card['suit'])}"


def hand_score(cards):
    """
    Calculate the optimal Blackjack score for a given hand.

    Aces count as 11 unless that would bust the hand, in which case
    they count as 1. This function handles multiple aces correctly.

    Args:
        cards (list[dict]): List of card dicts with 'rank' keys.

    Returns:
        int: Optimal Blackjack score (may exceed 21 if busted).
    """
    if not cards:
        return 0

    score = 0
    aces = 0

    for card in cards:
        rank = card["rank"]
        if rank in ("J", "Q", "K"):
            score += 10
        elif rank == "A":
            aces += 1
            score += 11
        else:
            score += int(rank)

    # Reduce aces from 11 to 1 as needed to avoid bust
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1

    return score


def is_pair(cards):
    """
    Determine if a two-card hand is a pair (eligible for split).

    Args:
        cards (list[dict]): Exactly two cards.

    Returns:
        bool: True if both cards share the same rank value.
    """
    if len(cards) != 2:
        return False
    rank_value = lambda r: 10 if r in ("J", "Q", "K") else r
    return rank_value(cards[0]["rank"]) == rank_value(cards[1]["rank"])


# ---------------------------------------------------------------------------
# Protocol Framing & Envelope
# ---------------------------------------------------------------------------

def build_msg(msg_type, payload):
    """
    Build a protocol-compliant message envelope.

    Per protocol_blueprint.md the envelope is exactly:
        { "msg_type": str, "player_id": "dealer", "timestamp": int, "payload": dict }

    Args:
        msg_type (str): One of the VALID_MSG_TYPES.
        payload (dict): Message-specific data.

    Returns:
        dict: The complete envelope dict.

    Raises:
        ValueError: If msg_type is not a recognised message type.
    """
    if msg_type not in VALID_MSG_TYPES:
        raise ValueError(f"Invalid msg_type: {msg_type!r}")
    return {
        "msg_type":  msg_type,
        "player_id": "dealer",
        "timestamp": int(time.time()),
        "payload":   payload,
    }


def frame_msg(msg):
    """
    Serialise a message dict to newline-delimited UTF-8 bytes.

    Args:
        msg (dict): Message envelope.

    Returns:
        bytes: JSON-encoded bytes ending with '\\n'.
    """
    return (json.dumps(msg) + "\n").encode("utf-8")


def validate_msg(raw):
    """
    Parse and validate a raw JSON string against the protocol schema.

    Checks that the envelope contains msg_type, player_id, timestamp,
    and payload, and that msg_type / player_id are recognised values.

    Args:
        raw (str): Raw JSON string (without the trailing newline).

    Returns:
        dict: Parsed message envelope.

    Raises:
        ValueError: On JSON parse failure or schema violation.
    """
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON: {exc}") from exc

    for field in ("msg_type", "player_id", "timestamp", "payload"):
        if field not in msg:
            raise ValueError(f"Missing required field: {field!r}")

    if msg["msg_type"] not in VALID_MSG_TYPES:
        raise ValueError(f"Unknown msg_type: {msg['msg_type']!r}")

    if msg["player_id"] not in VALID_PLAYER_IDS:
        raise ValueError(f"Unknown player_id: {msg['player_id']!r}")

    return msg


# ---------------------------------------------------------------------------
# Player Session
# ---------------------------------------------------------------------------

class PlayerSession:
    """
    Holds all per-player state that persists across rounds and reconnects.

    Attributes:
        player_id (str): Canonical ID, e.g. 'gambler_1'.
        name (str): Human-readable name provided at CONNECT time.
        balance (int): Current chip balance.
        sock (socket | None): Active TCP socket, None when disconnected.
        buf_in (str): Partial inbound data buffer (before full line received).
        buf_out (bytes): Outbound bytes queued to be flushed.
        hands (list[dict]): Per-round hand list; each hand is a dict with
            keys 'cards', 'score', 'bet', 'status'.
        bet (int): Bet for the current round (set via READY message).
        connected (bool): Whether the socket is currently live.
    """

    def __init__(self, player_id):
        self.player_id = player_id
        self.name      = player_id
        self.balance   = 0
        self.sock      = None
        self.buf_in    = ""
        self.buf_out   = b""
        self.hands     = []
        self.bet       = 0
        self.connected = False
        self.ready     = False

    def reset_round(self):
        """Clear per-round hand data while keeping balance and identity."""
        self.hands = []
        self.bet   = 0
        self.ready = False

    def make_hand(self, cards, bet):
        """
        Create a hand dict and append it to this player's hands list.

        Args:
            cards (list[dict]): Initial cards for the hand.
            bet (int): Wager on this hand.

        Returns:
            dict: The newly created hand dict.
        """
        hand = {
            "cards":  cards,
            "score":  hand_score(cards),
            "bet":    bet,
            "status": STATUS_ACTIVE,
        }
        self.hands.append(hand)
        return hand

    def to_state_dict(self, reveal_hole=False):
        """
        Serialise this player's public state for STATE_UPDATE / GAME_START.

        Args:
            reveal_hole (bool): Unused here; kept for interface symmetry.

        Returns:
            dict: Player state suitable for embedding in a payload.
        """
        return {
            "player_id": self.player_id,
            "name":      self.name,
            "balance":   self.balance,
            "bet":       self.bet,
            "hands":     [
                {
                    "cards":  h["cards"],
                    "score":  h["score"],
                    "bet":    h["bet"],
                    "status": h["status"],
                }
                for h in self.hands
            ],
        }


# ---------------------------------------------------------------------------
# Game State
# ---------------------------------------------------------------------------

class GameState:
    """
    Central game state container for the server.

    Holds the FSM state, deck, dealer hand, and both player sessions.
    All mutation happens through methods to keep the event loop clean.
    """

    def __init__(self):
        self.fsm_state    = ServerFSM.DISCONNECTED
        self.deck         = []
        self.dealer_hand  = []          # list of card dicts
        self.dealer_hole  = None        # face-down card (hidden until DEALER_TURN)
        self.dealer_up    = None        # face-up card shown to players
        self.dealer_score = 0
        self.current_turn = None        # "gambler_1" or "gambler_2"
        self.turn_index   = 0           # index into PLAYER_IDS for current turn
        self.players      = {
            pid: PlayerSession(pid) for pid in PLAYER_IDS
        }

    def transition(self, event):
        """
        Advance the FSM by applying event to the current state.

        Args:
            event (str): The event string triggering the transition.

        Returns:
            ServerFSM: The new FSM state.

        Raises:
            ValueError: If (current_state, event) is not a valid transition.
        """
        key = (self.fsm_state, event)
        if key not in FSM_TRANSITIONS:
            raise ValueError(
                f"Illegal FSM transition: state={self.fsm_state.name!r}, event={event!r}"
            )
        self.fsm_state = FSM_TRANSITIONS[key]
        return self.fsm_state

    def connected_players(self):
        """Return list of PlayerSession objects that are currently connected."""
        return [p for p in self.players.values() if p.connected]

    def connected_count(self):
        """Return the number of currently connected players."""
        return len(self.connected_players())

    def deal_card(self):
        """
        Pop and return the top card from the deck.

        Reshuffles a fresh deck if the current deck is exhausted.

        Returns:
            dict: A card dict with 'suit' and 'rank'.
        """
        if not self.deck:
            self.deck = build_deck()
        return self.deck.pop()

    def next_player_turn(self):
        """
        Advance current_turn to the next connected player who still has
        an ACTIVE hand, or return None if all players are done.

        Returns:
            str | None: Next player_id or None if all done.
        """
        # Check players in order: gambler_1 then gambler_2
        order = PLAYER_IDS[self.turn_index:] + PLAYER_IDS[:self.turn_index]
        for pid in order:
            p = self.players[pid]
            if not p.connected:
                continue
            if any(h["status"] == STATUS_ACTIVE for h in p.hands):
                self.current_turn = pid
                self.turn_index   = PLAYER_IDS.index(pid)
                return pid
        return None

    def all_players_done(self):
        """
        Return True when every connected player has no ACTIVE hands
        (all hands are STAND, BUSTED, or BLACKJACK).
        """
        for p in self.connected_players():
            if any(h["status"] == STATUS_ACTIVE for h in p.hands):
                return False
        return True

    def dealer_state_dict(self, reveal_hole=False):
        """
        Serialise dealer state for broadcast messages.

        Args:
            reveal_hole (bool): If True, include the hole card in the hand.

        Returns:
            dict: Dealer state dict.
        """
        if reveal_hole:
            cards = self.dealer_hand
            score = hand_score(cards)
        else:
            # Only the up card is visible; hole card shown as unknown
            cards = [self.dealer_up] if self.dealer_up else []
            score = hand_score(cards)
        return {
            "up_card": self.dealer_up,
            "score":   score,
            "cards":   cards,
        }


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class BlackjackServer:
    """
    Single-threaded Blackjack game server using selectors for I/O multiplexing.

    The main event loop calls sel.select(), then dispatches readable/writable
    events to the appropriate handlers.  All shared state lives in self.game,
    which is safe to mutate without locks because only one thread exists.
    """

    def __init__(self, port):
        self.port    = port
        self.sel     = selectors.DefaultSelector()
        self.game    = GameState()
        # Map from socket fileno -> player_id (or "server" for the listen sock)
        self.sock_to_player = {}

    # ------------------------------------------------------------------
    # Network Send / Receive
    # ------------------------------------------------------------------

    def _queue_send(self, player_id, msg):
        """
        Serialise msg and queue it in the player's outbound buffer.
        Registers EVENT_WRITE so the selector flushes it next iteration.

        Args:
            player_id (str): Target player's canonical ID.
            msg (dict): Message envelope to send.
        """
        p = self.game.players[player_id]
        if not p.connected or p.sock is None:
            return
        p.buf_out += frame_msg(msg)
        # Ensure we are watching for writability
        try:
            key = self.sel.get_key(p.sock)
            if not (key.events & selectors.EVENT_WRITE):
                self.sel.modify(
                    p.sock,
                    selectors.EVENT_READ | selectors.EVENT_WRITE,
                    data=player_id,
                )
        except KeyError:
            pass  # Socket already unregistered

    def send_to(self, player_id, msg):
        """
        Public interface: send a protocol message to one player.

        Args:
            player_id (str): Target player ID.
            msg (dict): Complete message envelope.
        """
        self._queue_send(player_id, msg)

    def broadcast(self, msg):
        """
        Send the same message to all currently connected players.

        Args:
            msg (dict): Complete message envelope.
        """
        for p in self.game.connected_players():
            self._queue_send(p.player_id, msg)

    def _flush_client(self, sock, player_id):
        """
        Flush as many bytes as possible from buf_out without blocking.
        If the buffer drains, deregister EVENT_WRITE.

        Args:
            sock (socket): The player's socket.
            player_id (str): The player whose buffer to flush.
        """
        p = self.game.players[player_id]
        if not p.buf_out:
            return
        try:
            sent = sock.send(p.buf_out)
            p.buf_out = p.buf_out[sent:]
        except (OSError, BrokenPipeError):
            self._disconnect_player(player_id)
            return

        if not p.buf_out:
            # Nothing left to send — stop monitoring for writability
            try:
                self.sel.modify(sock, selectors.EVENT_READ, data=player_id)
            except KeyError:
                pass

    def _read_client(self, sock, player_id):
        """
        Read available bytes from sock and process any complete lines.
        Partial lines are retained in buf_in for the next read.

        Args:
            sock (socket): The player's socket.
            player_id (str): The player who sent data.
        """
        p = self.game.players[player_id]
        try:
            data = sock.recv(4096)
        except (OSError, ConnectionResetError):
            data = b""

        if not data:
            # EOF / connection closed
            self._disconnect_player(player_id)
            return

        p.buf_in += data.decode("utf-8", errors="replace")

        # Process every complete newline-delimited JSON line
        while "\n" in p.buf_in:
            line, p.buf_in = p.buf_in.split("\n", 1)
            line = line.strip()
            if line:
                self._dispatch_message(player_id, line)

    # ------------------------------------------------------------------
    # Message Dispatch
    # ------------------------------------------------------------------

    def _dispatch_message(self, player_id, raw):
        """
        Validate and route an incoming raw JSON string to the correct handler.

        Args:
            player_id (str): The player who sent the message.
            raw (str): Raw JSON string (no trailing newline).
        """
        try:
            msg = validate_msg(raw)
        except ValueError as exc:
            self._send_error(player_id, "MALFORMED_PACKET", str(exc))
            return

        # For CONNECT messages the client does not yet know its assigned slot,
        # so it may send a placeholder player_id.  Override it with the
        # server-assigned slot ID before passing to the handler.
        if msg["msg_type"] == "CONNECT":
            msg["player_id"] = player_id
        elif msg["player_id"] != player_id:
            # All other message types must come from the correct slot.
            self._send_error(
                player_id, "INVALID_SENDER",
                f"Expected player_id={player_id!r}, got {msg['player_id']!r}."
            )
            return

        handlers = {
            "CONNECT":    self._handle_connect,
            "READY":      self._handle_ready,
            "MOVE":       self._handle_move,
            "DISCONNECT": self._handle_disconnect,
        }

        handler = handlers.get(msg["msg_type"])
        if handler is None:
            self._send_error(
                player_id, "UNEXPECTED_MSG",
                f"Server does not accept {msg['msg_type']!r} from clients."
            )
            return

        handler(player_id, msg["payload"])

    def _send_error(self, player_id, error_code, message):
        """
        Send an ERROR message to a specific player.

        Args:
            player_id (str): Recipient player ID.
            error_code (str): Short machine-readable code.
            message (str): Human-readable description.
        """
        msg = build_msg("ERROR", {"error_code": error_code, "message": message})
        self.send_to(player_id, msg)

    # ------------------------------------------------------------------
    # CONNECT Handler
    # ------------------------------------------------------------------

    def _handle_connect(self, player_id, payload):
        """
        Handle a CONNECT message from a client.

        Assigns the player their ID, records name/balance, and sends
        LOBBY_WAIT.  Advances FSM when both players are connected.

        Args:
            player_id (str): The player connecting.
            payload (dict): Must contain 'player_name' and 'balance'.
        """
        # Validate payload fields
        if "player_name" not in payload or "balance" not in payload:
            self._send_error(
                player_id, "INVALID_PAYLOAD",
                "CONNECT requires 'player_name' and 'balance'."
            )
            return

        balance = payload["balance"]
        if not isinstance(balance, (int, float)) or balance <= 0:
            self._send_error(
                player_id, "INVALID_BALANCE",
                "Balance must be a positive number."
            )
            return

        p = self.game.players[player_id]

        # --- Reconnect path ---
        # If a player with this name reconnects after a disconnect,
        # re-associate their session and restore state.
        if not p.connected:
            # Check if game is in progress and this slot was previously filled
            already_had_game = (
                self.game.fsm_state in (
                    ServerFSM.PLAYER_TURN, ServerFSM.BETTING,
                    ServerFSM.ALL_PLAYERS_DONE, ServerFSM.DEALER_TURN,
                )
                and p.name == payload["player_name"]
                and p.balance > 0
            )
            if already_had_game:
                p.connected = True
                print(f"[SERVER] {player_id} reconnected as {p.name}")
                # Restore state to both players
                state_msg = build_msg("STATE_UPDATE", self._build_state_payload())
                self.broadcast(state_msg)
                return

        # --- Fresh connect path ---
        p.name    = payload["player_name"]
        p.balance = int(balance)
        p.connected = True

        count = self.game.connected_count()

        try:
            if count == 1:
                self.game.transition("player_connected")  # -> WAITING_FOR_PLAYERS
            elif count == 2:
                self.game.transition("player_connected")  # -> BETTING
        except ValueError as exc:
            print(f"[SERVER] FSM error on connect: {exc}")

        # Send LOBBY_WAIT to this player
        lobby_msg = build_msg("LOBBY_WAIT", {
            "message":          "Waiting for Player 2 to join..." if count == 1
                                else "Both players connected. Place your bets!",
            "current_players":  count,
            "required_players": 2,
            "assigned_id":      player_id,
        })
        self.send_to(player_id, lobby_msg)

        # If second player just joined, also notify player 1
        if count == 2:
            other_id = "gambler_1" if player_id == "gambler_2" else "gambler_2"
            notify_msg = build_msg("LOBBY_WAIT", {
                "message":          "Both players connected. Place your bets!",
                "current_players":  2,
                "required_players": 2,
                "assigned_id":      other_id,
            })
            self.send_to(other_id, notify_msg)

        print(
            f"[SERVER] {player_id} ({p.name}) connected. "
            f"Balance: {p.balance}. FSM: {self.game.fsm_state.name}"
        )

    # ------------------------------------------------------------------
    # READY Handler
    # ------------------------------------------------------------------

    def _handle_ready(self, player_id, payload):
        """
        Handle a READY message (player has placed their bet).

        Validates bet amount against current balance.  When both players
        are ready, starts the round.

        Args:
            player_id (str): The player who is ready.
            payload (dict): Must contain 'bet_amount' and 'ready_status'.
        """
        if self.game.fsm_state != ServerFSM.BETTING:
            self._send_error(
                player_id, "WRONG_STATE",
                "Cannot place a bet outside of the BETTING phase."
            )
            return

        if "bet_amount" not in payload or "ready_status" not in payload:
            self._send_error(
                player_id, "INVALID_PAYLOAD",
                "READY requires 'bet_amount' and 'ready_status'."
            )
            return

        p = self.game.players[player_id]
        bet = payload["bet_amount"]

        if not isinstance(bet, (int, float)) or bet <= 0:
            self._send_error(
                player_id, "INVALID_BET",
                "Bet must be a positive number."
            )
            return

        bet = int(bet)

        if bet > p.balance:
            self._send_error(
                player_id, "INSUFFICIENT_BALANCE",
                f"Bet of {bet} exceeds your balance of {p.balance}."
            )
            return

        if not payload["ready_status"]:
            self._send_error(player_id, "NOT_READY", "ready_status must be true.")
            return

        p.bet   = bet
        p.ready = True
        print(f"[SERVER] {player_id} placed bet: {bet}. Ready: {p.ready}")

        # Check if both players are ready
        all_ready = all(
            self.game.players[pid].ready
            for pid in PLAYER_IDS
            if self.game.players[pid].connected
        )

        if all_ready and self.game.connected_count() == 2:
            self._start_round()

    # ------------------------------------------------------------------
    # Round Lifecycle
    # ------------------------------------------------------------------

    def _start_round(self):
        """
        Deal initial cards and broadcast GAME_START to all players.

        Transitions FSM: BETTING -> DEALING -> PLAYER_TURN.
        Each player receives 2 cards; dealer gets 1 up card and 1 hole card.
        """
        self.game.transition("wagers_ready")   # -> DEALING
        self.game.deck = build_deck()

        # Clear hands from any previous round (bets were just placed in READY)
        for p in self.game.players.values():
            p.hands = []

        # Deal 2 cards to each connected player
        for pid in PLAYER_IDS:
            p = self.game.players[pid]
            if p.connected:
                cards = [self.game.deal_card(), self.game.deal_card()]
                p.make_hand(cards, p.bet)
                p.balance -= p.bet  # Deduct bet from balance

        # Deal dealer cards: hole card first, then up card
        self.game.dealer_hole = self.game.deal_card()
        self.game.dealer_up   = self.game.deal_card()
        self.game.dealer_hand = [self.game.dealer_hole, self.game.dealer_up]

        # Set the first player's turn
        self.game.turn_index   = 0
        self.game.current_turn = PLAYER_IDS[0]

        self.game.transition("game_start")  # -> PLAYER_TURN

        # Broadcast GAME_START to all players
        players_data = []
        for pid in PLAYER_IDS:
            p = self.game.players[pid]
            if p.connected:
                players_data.append({
                    "player_id": pid,
                    "name":      p.name,
                    "balance":   p.balance,
                    "bet":       p.bet,
                    "hand":      p.hands[0]["cards"],
                    "hands":     p.to_state_dict()["hands"],
                })

        game_start_msg = build_msg("GAME_START", {
            "dealer_up_card": self.game.dealer_up,
            "dealer":         self.game.dealer_state_dict(reveal_hole=False),
            "players":        players_data,
            "current_turn":   self.game.current_turn,
        })
        self.broadcast(game_start_msg)
        print(f"[SERVER] Round started. First turn: {self.game.current_turn}")

    # ------------------------------------------------------------------
    # MOVE Handler
    # ------------------------------------------------------------------

    def _handle_move(self, player_id, payload):
        """
        Handle a MOVE message from a client.

        Validates: correct FSM state, correct player turn, valid action,
        valid hand_index.  Dispatches to the appropriate action handler.

        Args:
            player_id (str): The player attempting a move.
            payload (dict): Must contain 'action' and 'hand_index'.
        """
        if self.game.fsm_state != ServerFSM.PLAYER_TURN:
            self._send_error(
                player_id, "WRONG_STATE",
                "No moves accepted outside of PLAYER_TURN state."
            )
            return

        if self.game.current_turn != player_id:
            self._send_error(
                player_id, "NOT_YOUR_TURN",
                f"It is {self.game.current_turn}'s turn, not yours."
            )
            return

        if "action" not in payload or "hand_index" not in payload:
            self._send_error(
                player_id, "INVALID_PAYLOAD",
                "MOVE requires 'action' and 'hand_index'."
            )
            return

        action     = payload["action"]
        hand_index = payload["hand_index"]

        if action not in VALID_ACTIONS:
            self._send_error(
                player_id, "INVALID_ACTION",
                f"Action {action!r} is not valid. Choose from {sorted(VALID_ACTIONS)}."
            )
            return

        p = self.game.players[player_id]
        if hand_index < 0 or hand_index >= len(p.hands):
            self._send_error(
                player_id, "INVALID_HAND_INDEX",
                f"hand_index {hand_index} out of range (player has {len(p.hands)} hand(s))."
            )
            return

        hand = p.hands[hand_index]
        if hand["status"] != STATUS_ACTIVE:
            self._send_error(
                player_id, "HAND_NOT_ACTIVE",
                f"Hand {hand_index} is {hand['status']}; no further moves allowed."
            )
            return

        # Dispatch to action handler
        if action == "HIT":
            self._do_hit(player_id, hand_index)
        elif action == "STAND":
            self._do_stand(player_id, hand_index)
        elif action == "DOUBLE":
            self._do_double(player_id, hand_index)
        elif action == "SPLIT":
            self._do_split(player_id, hand_index)

    # ------------------------------------------------------------------
    # Action Handlers
    # ------------------------------------------------------------------

    def _do_hit(self, player_id, hand_index):
        """
        Deal one card to the specified hand.

        If the hand busts (score > 21), it is marked BUSTED and the
        turn is advanced.  Otherwise a STATE_UPDATE is broadcast.

        Args:
            player_id (str): The player hitting.
            hand_index (int): Index of the hand to hit.
        """
        p    = self.game.players[player_id]
        hand = p.hands[hand_index]

        new_card = self.game.deal_card()
        hand["cards"].append(new_card)
        hand["score"] = hand_score(hand["cards"])

        last_action = {
            "player_id":  player_id,
            "action":     "HIT",
            "card_dealt": new_card,
        }

        if hand["score"] > 21:
            hand["status"] = STATUS_BUSTED
            print(f"[SERVER] {player_id} BUSTED with score {hand['score']}")
            self._advance_turn(player_id, last_action=last_action)
        else:
            # FSM stays in PLAYER_TURN
            try:
                self.game.transition("hit_or_split")
            except ValueError:
                pass  # Already in PLAYER_TURN, some paths won't re-trigger
            self._broadcast_state(last_action)

    def _do_stand(self, player_id, hand_index):
        """
        Mark the specified hand as STAND and advance the turn.

        Args:
            player_id (str): The player standing.
            hand_index (int): Index of the hand standing.
        """
        p    = self.game.players[player_id]
        hand = p.hands[hand_index]

        hand["status"] = STATUS_STAND
        last_action = {
            "player_id":  player_id,
            "action":     "STAND",
            "card_dealt": None,
        }

        print(f"[SERVER] {player_id} STANDs on hand {hand_index} with score {hand['score']}")
        self._advance_turn(player_id, last_action=last_action)

    def _do_double(self, player_id, hand_index):
        """
        Double the bet, deal exactly one card, then stand.

        Only legal on the initial two-card hand.  Player must have
        sufficient balance to cover the additional bet.

        Args:
            player_id (str): The player doubling.
            hand_index (int): Index of the hand to double.
        """
        p    = self.game.players[player_id]
        hand = p.hands[hand_index]

        if len(hand["cards"]) != 2:
            self._send_error(
                player_id, "INVALID_MOVE",
                "Double down is only permitted on the initial two cards."
            )
            return

        if p.balance < hand["bet"]:
            self._send_error(
                player_id, "INSUFFICIENT_BALANCE",
                f"You need {hand['bet']} more chips to double down."
            )
            return

        # Deduct extra bet and double the wager
        p.balance    -= hand["bet"]
        hand["bet"]  *= 2

        # Deal exactly one card
        new_card = self.game.deal_card()
        hand["cards"].append(new_card)
        hand["score"] = hand_score(hand["cards"])

        if hand["score"] > 21:
            hand["status"] = STATUS_BUSTED
        else:
            hand["status"] = STATUS_STAND  # Must stand after double

        last_action = {
            "player_id":  player_id,
            "action":     "DOUBLE",
            "card_dealt": new_card,
        }
        print(
            f"[SERVER] {player_id} DOUBLED on hand {hand_index}. "
            f"New bet: {hand['bet']}. Score: {hand['score']}"
        )
        self._advance_turn(player_id, last_action=last_action)

    def _do_split(self, player_id, hand_index):
        """
        Split a two-card pair into two separate hands.

        Requires exactly two cards of equal rank value and sufficient
        balance to cover the second bet.

        Args:
            player_id (str): The player splitting.
            hand_index (int): Index of the pair hand.
        """
        p    = self.game.players[player_id]
        hand = p.hands[hand_index]

        if not is_pair(hand["cards"]):
            self._send_error(
                player_id, "INVALID_MOVE",
                "Split is only allowed on a pair (two cards of equal rank value)."
            )
            return

        if p.balance < hand["bet"]:
            self._send_error(
                player_id, "INSUFFICIENT_BALANCE",
                f"You need {hand['bet']} more chips to split."
            )
            return

        p.balance -= hand["bet"]  # Deduct second bet from balance

        # Create two new single-card hands from the split
        card_a, card_b = hand["cards"]
        new_hand_a = {
            "cards":  [card_a, self.game.deal_card()],
            "score":  0,
            "bet":    hand["bet"],
            "status": STATUS_ACTIVE,
        }
        new_hand_b = {
            "cards":  [card_b, self.game.deal_card()],
            "score":  0,
            "bet":    hand["bet"],
            "status": STATUS_ACTIVE,
        }
        new_hand_a["score"] = hand_score(new_hand_a["cards"])
        new_hand_b["score"] = hand_score(new_hand_b["cards"])

        # Replace the original hand with the two new hands
        p.hands[hand_index:hand_index + 1] = [new_hand_a, new_hand_b]

        last_action = {
            "player_id":  player_id,
            "action":     "SPLIT",
            "card_dealt": None,
        }
        print(f"[SERVER] {player_id} SPLIT hand {hand_index}")
        try:
            self.game.transition("hit_or_split")
        except ValueError:
            pass
        self._broadcast_state(last_action)

    # ------------------------------------------------------------------
    # Turn Management
    # ------------------------------------------------------------------

    def _advance_turn(self, current_player_id, last_action=None):
        """
        Move play to the next player or transition to DEALER_TURN.

        Checks if the current player has any remaining ACTIVE hands.
        If not, looks for the next player with ACTIVE hands.  If none
        exist, begins the dealer's turn.

        Args:
            current_player_id (str): Player whose action just finished.
            last_action (dict | None): Action that triggered the advance.
        """
        p = self.game.players[current_player_id]

        # Does this player still have ACTIVE hands?
        if any(h["status"] == STATUS_ACTIVE for h in p.hands):
            # Player still has active hands to play — stay on them
            # FSM stays PLAYER_TURN
            self._broadcast_state(last_action)
            return

        # This player is done — find next player
        next_pid = self._find_next_player(current_player_id)

        if next_pid is not None:
            self.game.current_turn = next_pid
            self.game.turn_index   = PLAYER_IDS.index(next_pid)
            try:
                self.game.transition("turn_ends")    # -> ALL_PLAYERS_DONE
                self.game.transition("next_player")  # -> PLAYER_TURN
            except ValueError:
                pass
            print(f"[SERVER] Turn advanced to {next_pid}")
            self._broadcast_state(last_action)
        else:
            # All players done — dealer's turn
            try:
                self.game.transition("turn_ends")  # -> ALL_PLAYERS_DONE
                self.game.transition("all_done")   # -> DEALER_TURN
            except ValueError:
                pass
            self._broadcast_state(last_action)
            self._dealer_play()

    def _find_next_player(self, done_player_id):
        """
        Find the next connected player (after done_player_id) who has
        at least one ACTIVE hand.

        Args:
            done_player_id (str): The player who just finished.

        Returns:
            str | None: Next player_id, or None if all are done.
        """
        idx   = PLAYER_IDS.index(done_player_id)
        order = PLAYER_IDS[idx + 1:] + PLAYER_IDS[:idx]
        for pid in order:
            p = self.game.players[pid]
            if p.connected and any(h["status"] == STATUS_ACTIVE for h in p.hands):
                return pid
        return None

    # ------------------------------------------------------------------
    # Dealer Play & Round Resolution
    # ------------------------------------------------------------------

    def _dealer_play(self):
        """
        Execute the dealer's turn: reveal hole card and hit until score >= 17.

        Transitions FSM: DEALER_TURN -> ROUND_END.
        Calls _resolve_round() after the dealer finishes drawing.
        """
        print("[SERVER] Dealer's turn begins.")
        # Dealer hand already has hole + up card; re-score the full hand
        self.game.dealer_score = hand_score(self.game.dealer_hand)

        # Dealer hits on soft 16 or below, stands on hard/soft 17+
        while self.game.dealer_score < 17:
            new_card = self.game.deal_card()
            self.game.dealer_hand.append(new_card)
            self.game.dealer_score = hand_score(self.game.dealer_hand)
            print(
                f"[SERVER] Dealer draws {card_label(new_card)}. "
                f"Score: {self.game.dealer_score}"
            )

        print(f"[SERVER] Dealer stands with score {self.game.dealer_score}.")
        self.game.transition("dealer_resolves")  # -> ROUND_END
        self._resolve_round()

    def _resolve_round(self):
        """
        Compare each player hand against the dealer score and compute payouts.

        Payout rules:
            - Blackjack (natural 21 on 2 cards): 3:2 payout
            - Win (beat dealer without busting): 1:1 payout
            - Push (tie): bet returned
            - Loss (busted or lower score than dealer): 0 payout

        Broadcasts GAME_OVER and transitions FSM to CLEANUP.
        """
        dealer_score  = self.game.dealer_score
        dealer_busted = dealer_score > 21

        dealer_hand_data = {
            "cards":  self.game.dealer_hand,
            "score":  dealer_score,
            "status": "BUSTED" if dealer_busted else "STAND",
        }

        results = []
        for pid in PLAYER_IDS:
            p = self.game.players[pid]
            if not p.connected:
                continue
            for idx, hand in enumerate(p.hands):
                player_score = hand["score"]
                busted       = hand["status"] == STATUS_BUSTED
                is_blackjack = (
                    player_score == 21
                    and len(hand["cards"]) == 2
                    and hand["status"] != STATUS_BUSTED
                )

                if busted:
                    outcome = "LOSS"
                    payout  = 0
                elif is_blackjack and not dealer_busted and dealer_score != 21:
                    outcome = "WIN"
                    payout  = int(hand["bet"] * 2.5)  # 3:2 pays back bet + 1.5x
                elif dealer_busted:
                    outcome = "WIN"
                    payout  = hand["bet"] * 2
                elif player_score > dealer_score:
                    outcome = "WIN"
                    payout  = hand["bet"] * 2
                elif player_score == dealer_score:
                    outcome = "PUSH"
                    payout  = hand["bet"]
                else:
                    outcome = "LOSS"
                    payout  = 0

                p.balance += payout
                results.append({
                    "player_id":     pid,
                    "name":          p.name,
                    "hand_index":    idx,
                    "player_score":  player_score,
                    "outcome":       outcome,
                    "payout":        payout,
                    "final_balance": p.balance,
                })
                print(
                    f"[SERVER] {pid} hand {idx}: score={player_score} "
                    f"outcome={outcome} payout={payout} balance={p.balance}"
                )

        game_over_msg = build_msg("GAME_OVER", {
            "dealer_hand": dealer_hand_data,
            "results":     results,
        })
        self.broadcast(game_over_msg)
        self.game.transition("game_over")  # -> CLEANUP
        self._cleanup()

    def _cleanup(self):
        """
        Reset per-round state and transition FSM based on remaining players.

        Decides next FSM state:
            - BETTING       if both players are still connected
            - WAITING_FOR_PLAYERS if only one remains
            - DISCONNECTED  if none remain
        """
        count = self.game.connected_count()
        if count == 2:
            self.game.transition("both_remain")    # -> BETTING
        elif count == 1:
            self.game.transition("one_remains")    # -> WAITING_FOR_PLAYERS
        else:
            self.game.transition("none_remain")    # -> DISCONNECTED

        # Reset ready flags for the next round
        for p in self.game.players.values():
            p.reset_round()

        print(f"[SERVER] Cleanup done. FSM: {self.game.fsm_state.name}")

    # ------------------------------------------------------------------
    # DISCONNECT Handler
    # ------------------------------------------------------------------

    def _handle_disconnect(self, player_id, payload):
        """
        Handle an intentional DISCONNECT message from a client.

        Args:
            player_id (str): The departing player.
            payload (dict): Contains 'reason' and 'message'.
        """
        reason  = payload.get("reason", "USER_QUIT")
        message = payload.get("message", "Player left the table.")
        print(f"[SERVER] {player_id} disconnected: {reason} — {message}")
        self._disconnect_player(player_id)

    def _disconnect_player(self, player_id):
        """
        Mark a player as disconnected, unregister their socket, and
        notify the other player.

        The player's session data (name, balance, hand) is retained so
        they can reconnect mid-game.

        Args:
            player_id (str): The player who disconnected.
        """
        p = self.game.players[player_id]
        if not p.connected:
            return  # Already disconnected; nothing to do

        p.connected = False
        if p.sock:
            try:
                self.sel.unregister(p.sock)
            except KeyError:
                pass
            try:
                p.sock.close()
            except OSError:
                pass
            p.sock = None

        print(f"[SERVER] {player_id} socket closed and unregistered.")

        # Notify the other player
        other_id = "gambler_1" if player_id == "gambler_2" else "gambler_2"
        other    = self.game.players[other_id]
        if other.connected:
            notify_msg = build_msg("LOBBY_WAIT", {
                "message":          f"{player_id} disconnected. Waiting for reconnection...",
                "current_players":  1,
                "required_players": 2,
                "assigned_id":      other_id,
            })
            self.send_to(other_id, notify_msg)

        # Transition FSM
        try:
            self.game.transition("disconnect")  # -> CLEANUP
        except ValueError:
            pass

        count = self.game.connected_count()
        if count == 1:
            try:
                self.game.transition("one_remains")  # -> WAITING_FOR_PLAYERS
            except ValueError:
                pass
        elif count == 0:
            try:
                self.game.transition("none_remain")  # -> DISCONNECTED
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # State Broadcast Helpers
    # ------------------------------------------------------------------

    def _build_state_payload(self, last_action=None, reveal_hole=False):
        """
        Build the payload dict for a STATE_UPDATE message.

        Args:
            last_action (dict | None): Description of the last action taken.
            reveal_hole (bool): Whether to reveal the dealer's hole card.

        Returns:
            dict: STATE_UPDATE payload.
        """
        players_state = []
        for pid in PLAYER_IDS:
            p = self.game.players[pid]
            if p.connected:
                players_state.append(p.to_state_dict())

        return {
            "last_action":  last_action,
            "dealer":       self.game.dealer_state_dict(reveal_hole=reveal_hole),
            "players":      players_state,
            "current_turn": self.game.current_turn,
        }

    def _broadcast_state(self, last_action):
        """
        Broadcast a STATE_UPDATE to all connected players.

        Args:
            last_action (dict | None): The action that triggered this update.
        """
        payload = self._build_state_payload(last_action=last_action)
        msg     = build_msg("STATE_UPDATE", payload)
        self.broadcast(msg)

    # ------------------------------------------------------------------
    # Connection Acceptance
    # ------------------------------------------------------------------

    def _accept_connection(self, server_sock):
        """
        Accept a new incoming TCP connection and register it with the selector.

        Assigns the new socket to the first available player slot
        (gambler_1, then gambler_2).  Rejects a third client with an error.

        Args:
            server_sock (socket): The listening server socket.
        """
        conn, addr = server_sock.accept()
        conn.setblocking(False)

        # Find an open slot
        assigned = None
        for pid in PLAYER_IDS:
            if not self.game.players[pid].connected:
                assigned = pid
                break

        if assigned is None:
            # Table is full
            err = build_msg("ERROR", {
                "error_code": "TABLE_FULL",
                "message":    "The table is full (2 players maximum).",
            })
            conn.sendall(frame_msg(err))
            conn.close()
            print(f"[SERVER] Rejected connection from {addr}: table full.")
            return

        self.game.players[assigned].sock = conn
        self.sel.register(
            conn,
            selectors.EVENT_READ,
            data=assigned,
        )
        self.sock_to_player[conn.fileno()] = assigned
        print(f"[SERVER] New connection from {addr} assigned to {assigned}.")

    # ------------------------------------------------------------------
    # Main Event Loop
    # ------------------------------------------------------------------

    def run(self):
        """
        Start the server and enter the selectors event loop.

        Binds to 0.0.0.0:<port>, registers the listening socket,
        then loops forever dispatching readable/writable events.
        """
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("0.0.0.0", self.port))
        server_sock.listen(2)
        server_sock.setblocking(False)

        self.sel.register(server_sock, selectors.EVENT_READ, data="server")
        print(f"[SERVER] Blackjack dealer listening on 0.0.0.0:{self.port}")

        try:
            while True:
                events = self.sel.select(timeout=None)
                for key, mask in events:
                    if key.data == "server":
                        self._accept_connection(key.fileobj)
                    else:
                        player_id = key.data
                        sock      = key.fileobj
                        if mask & selectors.EVENT_READ:
                            self._read_client(sock, player_id)
                        if mask & selectors.EVENT_WRITE:
                            self._flush_client(sock, player_id)
        except KeyboardInterrupt:
            print("\n[SERVER] Shutting down.")
        finally:
            self.sel.close()
            server_sock.close()


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def parse_args():
    """
    Parse command-line arguments for the server.

    Returns:
        argparse.Namespace: Parsed arguments with attribute 'port'.
    """
    parser = argparse.ArgumentParser(
        prog="server.py",
        description="2-Player Blackjack Dealer Server (CS 457)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 server.py -p 8080\n"
            "  python3 server.py -h\n"
        ),
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        required=True,
        metavar="PORT",
        help="TCP port to listen on (binds to 0.0.0.0).",
    )
    return parser.parse_args()


def main():
    """Entry point: parse args, create server, run event loop."""
    args = parse_args()

    if args.port < 1 or args.port > 65535:
        print("[ERROR] Port must be between 1 and 65535.", file=sys.stderr)
        sys.exit(1)

    server = BlackjackServer(args.port)
    server.run()


if __name__ == "__main__":
    main()
