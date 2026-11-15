"""
client.py — 2-Player Blackjack Player Client
CS 457 Networking — Sprint 2

Usage:
    python3 client.py -i <hostname> -p <port>
    python3 client.py -h

Architecture:
    - DNS resolved via socket.gethostbyname(); socket.gaierror caught explicitly
    - Blocking TCP socket with newline-delimited JSON framing
    - Local client FSM tracks display state (no game logic lives here)
    - All rendering via ASCII art board drawn to stdout
"""

import argparse
import json
import socket
import sys
import time


# ---------------------------------------------------------------------------
# Protocol Constants (must match protocol_blueprint.md exactly)
# ---------------------------------------------------------------------------

VALID_MSG_TYPES = {
    "CONNECT", "LOBBY_WAIT", "READY", "GAME_START",
    "MOVE", "STATE_UPDATE", "GAME_OVER", "ERROR", "DISCONNECT"
}
VALID_ACTIONS = {"HIT", "STAND", "DOUBLE", "SPLIT"}

SUIT_SYMBOLS = {"HEARTS": "♥", "DIAMONDS": "♦", "CLUBS": "♣", "SPADES": "♠"}


# ---------------------------------------------------------------------------
# Client Display State
# ---------------------------------------------------------------------------

class ClientState:
    """
    Lightweight local FSM for display logic only.

    Tracks the client's current phase so handlers know which
    prompt or screen to show.  No game logic runs client-side.
    """

    CONNECTING  = "CONNECTING"
    LOBBY_WAIT  = "LOBBY_WAIT"
    BETTING     = "BETTING"
    WAITING     = "WAITING"
    MY_TURN     = "MY_TURN"
    DEALER_TURN = "DEALER_TURN"
    GAME_OVER   = "GAME_OVER"
    DONE        = "DONE"

    def __init__(self):
        self.phase      = self.CONNECTING
        self.player_id  = None   # "gambler_1" or "gambler_2"
        self.name       = None   # Player's chosen display name
        self.balance    = 0
        self.last_state = None   # Last STATE_UPDATE payload for redraw


# ---------------------------------------------------------------------------
# DNS Resolution
# ---------------------------------------------------------------------------

def resolve_host(hostname):
    """
    Resolve a DNS hostname to an IP address string.

    Uses socket.gethostbyname().  If resolution fails (DNS error,
    unreachable DNS server, unknown host), prints a user-friendly
    error message and exits with status code 1.  The raw traceback
    is never shown to the user.

    Args:
        hostname (str): The DNS hostname to resolve (e.g. 'server.smith.edu').

    Returns:
        str: The resolved IPv4 address string.

    Exits:
        sys.exit(1) on socket.gaierror.
    """
    try:
        ip = socket.gethostbyname(hostname)
        return ip
    except socket.gaierror as exc:
        print(
            f"\n[ERROR] Could not resolve hostname: '{hostname}'\n"
            f"  Reason : {exc.strerror} (error {exc.errno})\n"
            f"\n  Please check:\n"
            f"    • Your router/DNS configuration\n"
            f"    • That the hostname is spelled correctly\n"
            f"    • That your network connection is active\n",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# TCP Connection
# ---------------------------------------------------------------------------

def connect_to_server(ip, port):
    """
    Open a blocking TCP connection to the game server.

    Args:
        ip (str): Resolved IPv4 address of the server.
        port (int): TCP port the server is listening on.

    Returns:
        socket.socket: Connected TCP socket.

    Exits:
        sys.exit(1) on connection failure.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((ip, port))
        return sock
    except (OSError, ConnectionRefusedError) as exc:
        print(
            f"\n[ERROR] Could not connect to {ip}:{port}\n"
            f"  Reason: {exc}\n"
            f"\n  Please verify the server is running and the port is correct.\n",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Framing — Send & Receive
# ---------------------------------------------------------------------------

def send_msg(sock, msg):
    """
    Serialise a message dict and send it over the socket with a newline delimiter.

    Per protocol_blueprint.md framing: each message is JSON + '\\n' encoded
    as UTF-8.

    Args:
        sock (socket.socket): Connected TCP socket.
        msg (dict): Protocol message envelope.

    Raises:
        OSError: If the send fails (caller should handle gracefully).
    """
    data = (json.dumps(msg) + "\n").encode("utf-8")
    sock.sendall(data)


def recv_msg(sock, buf):
    """
    Read bytes from the socket into buf and return the next complete message.

    First checks if a complete newline-delimited message is already in buf.
    If not, reads chunks from the socket until a complete line is found.

    Args:
        sock (socket.socket): Connected TCP socket.
        buf (list): Single-element list acting as a mutable string buffer,
                    e.g. ``['']``.

    Returns:
        dict | None: Parsed message dict, or None if connection closed or error.

    Raises:
        ConnectionError: If the server closed the connection.
    """
    # 1. Drain any complete lines already in the buffer first
    while "\n" in buf[0]:
        line, buf[0] = buf[0].split("\n", 1)
        line = line.strip()
        if line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    # 2. Only read from the socket if no complete line is in buf
    while True:
        try:
            chunk = sock.recv(4096)
        except (OSError, ConnectionResetError) as exc:
            raise ConnectionError(f"Socket read error: {exc}") from exc

        if not chunk:
            raise ConnectionError("Server closed the connection.")

        buf[0] += chunk.decode("utf-8", errors="replace")

        if "\n" in buf[0]:
            line, buf[0] = buf[0].split("\n", 1)
            line = line.strip()
            if line:
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue


# ---------------------------------------------------------------------------
# Message Builder
# ---------------------------------------------------------------------------

def build_msg(msg_type, player_id, payload):
    """
    Build a protocol-compliant message envelope for client→server messages.

    Args:
        msg_type (str): One of the VALID_MSG_TYPES.
        player_id (str): The client's assigned player ID.
        payload (dict): Message-specific data.

    Returns:
        dict: Complete envelope with msg_type, player_id, timestamp, payload.
    """
    return {
        "msg_type":  msg_type,
        "player_id": player_id,
        "timestamp": int(time.time()),
        "payload":   payload,
    }


# ---------------------------------------------------------------------------
# Input Helpers
# ---------------------------------------------------------------------------

def prompt_bet(balance):
    """
    Interactively prompt the player for a bet amount.

    Validates that the input is a positive integer no greater than
    the player's current balance.  Re-prompts on invalid input.

    Args:
        balance (int): The player's current chip balance.

    Returns:
        int: A validated bet amount in the range [1, balance].
    """
    while True:
        try:
            raw = input(f"  Enter bet (1 – {balance}): ").strip()
            bet = int(raw)
            if bet < 1:
                print("  ✗ Bet must be at least 1.")
                continue
            if bet > balance:
                print(f"  ✗ Bet cannot exceed your balance of {balance}.")
                continue
            return bet
        except ValueError:
            print("  ✗ Please enter a whole number.")
        except (EOFError, KeyboardInterrupt):
            print("\n  Exiting.")
            sys.exit(0)


def prompt_move(hand_cards, score, can_double, can_split):
    """
    Display the player's current hand and prompt for a game action.

    Available options depend on game rules:
        - HIT   : always available
        - STAND : always available
        - DOUBLE: only when hand has exactly 2 cards and balance allows
        - SPLIT : only when hand is a pair (2 cards of equal rank value)

    Args:
        hand_cards (list[dict]): Current cards in the active hand.
        score (int): Current hand score.
        can_double (bool): True if doubling is allowed.
        can_split (bool): True if splitting is allowed.

    Returns:
        str: One of 'HIT', 'STAND', 'DOUBLE', 'SPLIT'.
    """
    options = ["HIT", "STAND"]
    if can_double:
        options.append("DOUBLE")
    if can_split:
        options.append("SPLIT")

    card_str = "  ".join(card_label(c) for c in hand_cards)
    print(f"\n  Your hand : {card_str}  (score: {score})")
    print(f"  Options   : {' | '.join(options)}")

    while True:
        try:
            choice = input("  Your move : ").strip().upper()
            if choice in options:
                return choice
            print(f"  ✗ Invalid choice. Choose from: {' | '.join(options)}")
        except (EOFError, KeyboardInterrupt):
            print("\n  Exiting.")
            sys.exit(0)


# ---------------------------------------------------------------------------
# Card Helpers & Rendering
# ---------------------------------------------------------------------------

def hand_score(cards):
    """
    Calculate the optimal Blackjack score for a hand.

    Aces count as 11 unless that would bust the hand, in which case
    they count as 1.

    Args:
        cards (list[dict]): List of card dicts with 'rank' keys.

    Returns:
        int: Optimal Blackjack score.
    """
    if not cards:
        return 0
    score = 0
    aces = 0
    for card in cards:
        rank = card.get("rank", "0")
        if rank in ("J", "Q", "K"):
            score += 10
        elif rank == "A":
            aces += 1
            score += 11
        else:
            try:
                score += int(rank)
            except ValueError:
                pass
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    return score


def card_label(card):
    """
    Return a compact, human-readable card label such as 'A♥' or '10♠'.

    Args:
        card (dict): Card dict with 'rank' and 'suit' keys.

    Returns:
        str: Display label for the card.
    """
    if card is None:
        return "[??]"
    symbol = SUIT_SYMBOLS.get(card.get("suit", ""), card.get("suit", "?"))
    return f"{card.get('rank', '?')}{symbol}"


# ---------------------------------------------------------------------------
# CLI Board Rendering
# ---------------------------------------------------------------------------

BOARD_WIDTH = 70  # Inner width of the board box


def _box_line(text="", width=BOARD_WIDTH):
    """
    Return a padded, bordered line: '║ <text padded to width - 2> ║'.
    Guarantees consistent border alignment without line overflow.
    """
    inner_width = width - 2
    if len(text) > inner_width:
        text = text[:inner_width - 1] + "…"
    return f"║ {text:<{inner_width}} ║"


def render_board(payload, my_id):
    """
    Render a full ASCII game board to stdout showing all player hands
    and the dealer's visible card.

    Args:
        payload (dict): A STATE_UPDATE or GAME_START payload.
        my_id (str): This client's player_id for 'You' labelling.
    """
    print()
    print(f"╔{'═' * BOARD_WIDTH}╗")
    print(_box_line(f"{'♠  BLACKJACK TABLE  ♠':^{BOARD_WIDTH - 2}}"))
    print(f"╠{'═' * BOARD_WIDTH}╣")

    # --- Dealer row ---
    dealer       = payload.get("dealer", {})
    dealer_cards = dealer.get("cards", [])
    up_card      = dealer.get("up_card") or payload.get("dealer_up_card")
    d_score      = dealer.get("score")
    if d_score is None:
        d_score = hand_score([up_card]) if up_card else "?"

    if dealer_cards and len(dealer_cards) > 1:
        # Full reveal (GAME_OVER path uses full dealer hand)
        d_display = "  ".join(card_label(c) for c in dealer_cards)
    elif up_card:
        d_display = f"{card_label(up_card)}  [??]"
    else:
        d_display = "[??]  [??]"

    print(_box_line(f"  DEALER:  {d_display:<24}  Score: {d_score}"))
    print(f"╠{'═' * BOARD_WIDTH}╣")

    # --- Player rows ---
    current_turn = payload.get("current_turn", "")
    players      = payload.get("players", [])

    for idx, player in enumerate(players):
        if idx > 0:
            print(f"╠{'═' * BOARD_WIDTH}╣")

        pid          = player.get("player_id", "?")
        balance      = player.get("balance", 0)
        is_me        = (pid == my_id)
        # Use the player's chosen name when the server provides it;
        # fall back to player_id if the name field is absent.
        display_name = player.get("name", pid)
        label        = f"{display_name} (You)" if is_me else display_name

        hands = player.get("hands", [])
        if not hands:
            # GAME_START uses 'hand' key instead of 'hands'
            raw_hand = player.get("hand", [])
            if raw_hand:
                score = hand_score(raw_hand)
                bet = player.get("bet", 0)
                hands = [{"cards": raw_hand, "score": score, "bet": bet, "status": "ACTIVE"}]

        # Compute total bet for this player across all active/split hands
        if hands:
            total_bet = sum(h.get("bet", 0) for h in hands)
        else:
            total_bet = player.get("bet", 0)

        # Header row for each player showing name, balance, and bet
        print(_box_line(f"  {label:<22} Balance: ${balance:<6} Total Bet: ${total_bet}"))

        for i, hand in enumerate(hands):
            cards  = hand.get("cards", [])
            score  = hand.get("score", 0)
            bet    = hand.get("bet", 0)
            status = hand.get("status", "ACTIVE")

            cards_str = "  ".join(card_label(c) for c in cards)
            print(_box_line(
                f"  Hand {i}: [{cards_str}]  Score: {score:<2}  Bet: ${bet:<4}  [{status}]"
            ))

        # Turn status banner (single-column characters to prevent right border misalignment)
        if current_turn == pid == my_id:
            banner = "► YOUR TURN"
        elif current_turn == pid:
            banner = f"Waiting on {display_name}..."
        elif current_turn is None:
            banner = "Dealer's Turn — Drawing cards..."
        else:
            banner = "Waiting..."

        print(_box_line(f"{banner:^{BOARD_WIDTH - 2}}"))

    print(f"╚{'═' * BOARD_WIDTH}╝")
    print()


def render_lobby(payload, my_id):
    """
    Render a lobby waiting screen.

    Args:
        payload (dict): LOBBY_WAIT payload from server.
        my_id (str): This client's player_id.
    """
    msg      = payload.get("message", "Waiting...")
    current  = payload.get("current_players", 1)
    required = payload.get("required_players", 2)
    assigned = payload.get("assigned_id", my_id)

    print()
    print(f"╔{'═' * BOARD_WIDTH}╗")
    print(_box_line(f"{'♠  BLACKJACK LOBBY  ♠':^{BOARD_WIDTH - 2}}"))
    print(f"╠{'═' * BOARD_WIDTH}╣")
    print(_box_line(f"  Your seat : {assigned}"))
    print(_box_line(f"  Players   : {current} / {required}"))
    print(_box_line())
    print(_box_line(f"  {msg}"))
    print(f"╚{'═' * BOARD_WIDTH}╝")
    print()


def render_game_over(payload, my_id):
    """
    Render the final score table after the round ends.

    Args:
        payload (dict): GAME_OVER payload from server.
        my_id (str): This client's player_id for 'You' labelling.
    """
    dealer_data = payload.get("dealer_hand", {})
    d_cards     = dealer_data.get("cards", [])
    d_score     = dealer_data.get("score", "?")
    d_status    = dealer_data.get("status", "")
    d_str       = "  ".join(card_label(c) for c in d_cards)

    results = payload.get("results", [])

    print()
    print(f"╔{'═' * BOARD_WIDTH}╗")
    print(_box_line(f"{'===  GAME OVER  ===':^{BOARD_WIDTH - 2}}"))
    print(f"╠{'═' * BOARD_WIDTH}╣")
    print(_box_line(f"  DEALER FINAL: [{d_str}]  Score: {d_score}  [{d_status}]"))
    print(f"╠{'═' * BOARD_WIDTH}╣")

    for idx, r in enumerate(results):
        if idx > 0:
            print(f"╠{'═' * BOARD_WIDTH}╣")

        pid     = r.get("player_id", "?")
        h_idx   = r.get("hand_index", 0)
        score   = r.get("player_score", 0)
        outcome = r.get("outcome", "?")
        payout  = r.get("payout", 0)
        balance = r.get("final_balance", 0)
        # Use player name if provided in result, otherwise fall back to player_id
        name    = r.get("name", pid)
        label   = f"{name} (You)" if pid == my_id else name

        # Single-width outcome formatting
        if outcome == "WIN":
            outcome_str = f"[WIN]  (+${payout})"
        elif outcome == "LOSS":
            outcome_str = f"[LOSS] ($0)"
        else:
            outcome_str = f"[PUSH] (${payout} returned)"

        print(_box_line(f"  {label:<20} Hand {h_idx}: Score {score:<3} {outcome_str}"))
        print(_box_line(f"  {'':20} Final Balance: ${balance}"))

    print(f"╚{'═' * BOARD_WIDTH}╝")
    print()


def render_error(payload):
    """
    Render a server error message box to stderr.

    Args:
        payload (dict): ERROR payload with 'error_code' and 'message'.
    """
    code = payload.get("error_code", "UNKNOWN")
    msg  = payload.get("message", "An error occurred.")
    print(f"\n  ⚠  SERVER ERROR [{code}]: {msg}\n", file=sys.stderr)


# ---------------------------------------------------------------------------
# Message Handlers
# ---------------------------------------------------------------------------

def handle_lobby_wait(msg, state, sock):
    """
    Process a LOBBY_WAIT message from the server.

    Updates the client's player_id if the server assigned one, then
    renders the lobby waiting screen.

    Args:
        msg (dict): Full message envelope.
        state (ClientState): Mutable client state object.
        sock (socket.socket): Active TCP socket (unused here, kept for interface).
    """
    payload = msg.get("payload", {})
    assigned = payload.get("assigned_id")
    if assigned:
        state.player_id = assigned

    state.phase = ClientState.LOBBY_WAIT
    render_lobby(payload, state.player_id)


def handle_game_start(msg, state, sock):
    """
    Process a GAME_START message: render the initial board and
    transition to WAITING or MY_TURN.

    Args:
        msg (dict): Full message envelope.
        state (ClientState): Mutable client state object.
        sock (socket.socket): Active TCP socket.
    """
    payload      = msg.get("payload", {})
    current_turn = payload.get("current_turn")
    state.last_state = payload

    # Find our balance from the players list and cache opponent names
    for p in payload.get("players", []):
        if p.get("player_id") == state.player_id:
            state.balance = p.get("balance", state.balance)
        # Store name in state so other renders (lobby, prompts) can use it
        pid  = p.get("player_id")
        name = p.get("name")
        if pid and name:
            if not hasattr(state, "player_names"):
                state.player_names = {}
            state.player_names[pid] = name

    if current_turn == state.player_id:
        state.phase = ClientState.MY_TURN
    else:
        state.phase = ClientState.WAITING

    render_board(payload, state.player_id)


def handle_state_update(msg, state, sock):
    """
    Process a STATE_UPDATE: re-render the board and update local phase.

    Args:
        msg (dict): Full message envelope.
        state (ClientState): Mutable client state object.
        sock (socket.socket): Active TCP socket.
    """
    payload      = msg.get("payload", {})
    current_turn = payload.get("current_turn")
    state.last_state = payload

    # Update our balance from the state and cache player names
    for p in payload.get("players", []):
        if p.get("player_id") == state.player_id:
            state.balance = p.get("balance", state.balance)
        pid  = p.get("player_id")
        name = p.get("name")
        if pid and name:
            if not hasattr(state, "player_names"):
                state.player_names = {}
            state.player_names[pid] = name

    if current_turn is None:
        state.phase = ClientState.DEALER_TURN
    elif current_turn == state.player_id:
        state.phase = ClientState.MY_TURN
    else:
        state.phase = ClientState.WAITING

    render_board(payload, state.player_id)


def handle_game_over(msg, state, sock):
    """
    Process a GAME_OVER message: display the final score table and
    ask the player if they want to play another round.

    If the player wants to play again, sends a READY message with their
    new bet.  Otherwise sends DISCONNECT and exits.

    Args:
        msg (dict): Full message envelope.
        state (ClientState): Mutable client state object.
        sock (socket.socket): Active TCP socket.
    """
    payload = msg.get("payload", {})

    # Update our final balance from results
    for r in payload.get("results", []):
        if r.get("player_id") == state.player_id and r.get("hand_index", 0) == 0:
            state.balance = r.get("final_balance", state.balance)
            break

    state.phase = ClientState.GAME_OVER
    render_game_over(payload, state.player_id)

    if state.balance <= 0:
        print("  You have no chips remaining. Thanks for playing!")
        _send_disconnect(sock, state.player_id)
        sys.exit(0)

    # Prompt to play again
    while True:
        try:
            choice = input(
                f"  Play another round? (Balance: ${state.balance}) [y/n]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "n"

        if choice == "y":
            bet = prompt_bet(state.balance)
            ready_msg = build_msg("READY", state.player_id, {
                "bet_amount":   bet,
                "ready_status": True,
            })
            send_msg(sock, ready_msg)
            state.phase = ClientState.WAITING
            break
        elif choice == "n":
            _send_disconnect(sock, state.player_id)
            print("  Thanks for playing! Goodbye.")
            sys.exit(0)
        else:
            print("  Please enter 'y' or 'n'.")


def handle_error(msg, state):
    """
    Process an ERROR message from the server.

    Renders the error and returns control to the caller, which will
    re-prompt the player if appropriate.

    Args:
        msg (dict): Full message envelope.
        state (ClientState): Mutable client state object (not modified here).
    """
    payload = msg.get("payload", {})
    render_error(payload)


def _send_disconnect(sock, player_id):
    """
    Send a DISCONNECT message to the server before closing.

    Args:
        sock (socket.socket): Active TCP socket.
        player_id (str): This client's player ID.
    """
    disconnect_msg = build_msg("DISCONNECT", player_id, {
        "reason":  "USER_QUIT",
        "message": "Player left the table.",
    })
    try:
        send_msg(sock, disconnect_msg)
    except OSError:
        pass  # Socket may already be closed


# ---------------------------------------------------------------------------
# Main Game Loop
# ---------------------------------------------------------------------------

def main_loop(sock, state):
    """
    Main receive-dispatch-action loop for the client.

    Listens for server messages and dispatches them to the appropriate
    handler.  When it is this client's turn, prompts the player for a
    move and sends the MOVE message.

    Args:
        sock (socket.socket): Connected TCP socket.
        state (ClientState): Mutable client state object.
    """
    buf = [""]  # Mutable buffer for recv_msg

    while state.phase != ClientState.DONE:
        # --- Receive and handle one message ---
        try:
            msg = recv_msg(sock, buf)
        except ConnectionError as exc:
            print(f"\n[ERROR] Lost connection to server: {exc}", file=sys.stderr)
            sys.exit(1)

        if msg is None:
            continue  # Partial data; keep reading

        msg_type = msg.get("msg_type", "")

        if msg_type == "LOBBY_WAIT":
            handle_lobby_wait(msg, state, sock)

        elif msg_type == "GAME_START":
            handle_game_start(msg, state, sock)

        elif msg_type == "STATE_UPDATE":
            handle_state_update(msg, state, sock)

        elif msg_type == "GAME_OVER":
            handle_game_over(msg, state, sock)
            # After handle_game_over returns, we may be in WAITING (play again)
            # or the function will have called sys.exit(). Continue the loop.

        elif msg_type == "ERROR":
            handle_error(msg, state)

        elif msg_type == "DISCONNECT":
            print("\n  The server has ended the session.")
            sys.exit(0)

        else:
            print(f"\n  [WARN] Unrecognised message type: {msg_type!r}")

        # --- After processing, take action if it is our turn ---
        _maybe_take_turn(sock, state, buf)


def _maybe_take_turn(sock, state, buf):
    """
    If the client is in MY_TURN phase, prompt for action and send MOVE.

    Inspects current game state, prompts for active hand actions,
    sends MOVE, and waits for STATE_UPDATE / GAME_OVER / ERROR responses.

    Args:
        sock (socket.socket): Connected TCP socket.
        state (ClientState): Mutable client state object.
        buf (list): Mutable string buffer for recv_msg.
    """
    while state.phase == ClientState.MY_TURN:
        payload = state.last_state or {}
        players = payload.get("players", [])

        # Find our hands in the last known state
        my_hands = []
        for p in players:
            if p.get("player_id") == state.player_id:
                my_hands = p.get("hands", [])
                # Handle GAME_START which uses single 'hand' key
                if not my_hands and "hand" in p:
                    raw_hand = p["hand"]
                    bet = p.get("bet", 0)
                    score = hand_score(raw_hand)
                    my_hands = [{
                        "cards": raw_hand,
                        "score": score,
                        "bet": bet,
                        "status": "ACTIVE",
                    }]
                break

        # Find the first ACTIVE hand index
        active_index = None
        for i, h in enumerate(my_hands):
            if h.get("status") == "ACTIVE":
                active_index = i
                break

        if active_index is None:
            # All hands completed or stood for this player
            state.phase = ClientState.WAITING
            break

        hand = my_hands[active_index]
        cards = hand.get("cards", [])
        score = hand.get("score", 0)
        bet = hand.get("bet", 0)
        can_double = len(cards) == 2 and state.balance >= bet
        can_split = len(cards) == 2 and _is_pair(cards) and state.balance >= bet

        action = prompt_move(cards, score, can_double, can_split)

        move_msg = build_msg("MOVE", state.player_id, {
            "action": action,
            "hand_index": active_index,
        })
        try:
            send_msg(sock, move_msg)
        except OSError as exc:
            print(f"\n[ERROR] Failed to send move: {exc}", file=sys.stderr)
            sys.exit(1)

        # Wait for server response (STATE_UPDATE or ERROR)
        while True:
            try:
                response = recv_msg(sock, buf)
            except ConnectionError as exc:
                print(f"\n[ERROR] Lost connection to server: {exc}", file=sys.stderr)
                sys.exit(1)

            if response is None:
                continue

            resp_type = response.get("msg_type", "")

            if resp_type == "STATE_UPDATE":
                handle_state_update(response, state, sock)
                # Outer while loop will check state.phase and next active hand
                break

            elif resp_type == "GAME_OVER":
                handle_game_over(response, state, sock)
                return

            elif resp_type == "ERROR":
                handle_error(response, state)
                # Re-prompt in next loop iteration
                break

            elif resp_type == "LOBBY_WAIT":
                handle_lobby_wait(response, state, sock)
                return

            else:
                print(f"\n  [WARN] Unexpected message during turn: {resp_type!r}")


def _is_pair(cards):
    """
    Return True if two cards share the same rank value (for split eligibility).

    Args:
        cards (list[dict]): Exactly two card dicts.

    Returns:
        bool: True if the cards form a splittable pair.
    """
    if len(cards) != 2:
        return False
    rank_val = lambda r: 10 if r in ("J", "Q", "K") else r
    return rank_val(cards[0]["rank"]) == rank_val(cards[1]["rank"])


# ---------------------------------------------------------------------------
# Bet Prompt at Session Start
# ---------------------------------------------------------------------------

def prompt_initial_bet(sock, state):
    """
    Prompt the player for their opening bet and send a READY message.

    Called once after both players have connected and the server
    sends a LOBBY_WAIT with current_players == 2.

    Args:
        sock (socket.socket): Connected TCP socket.
        state (ClientState): Mutable client state object.
    """
    print(f"\n  It's time to place your bet! (Balance: ${state.balance})")
    bet = prompt_bet(state.balance)

    ready_msg = build_msg("READY", state.player_id, {
        "bet_amount":   bet,
        "ready_status": True,
    })
    send_msg(sock, ready_msg)
    state.phase = ClientState.WAITING
    print(f"  Bet of ${bet} placed. Waiting for the other player...")


# ---------------------------------------------------------------------------
# CLI Argument Parsing
# ---------------------------------------------------------------------------

def parse_args():
    """
    Parse command-line arguments for the client.

    Required arguments: -i (hostname) and -p (port).
    Optional:           -h (help).

    Returns:
        argparse.Namespace: Parsed arguments with 'hostname' and 'port'.
    """
    parser = argparse.ArgumentParser(
        prog="client.py",
        description="2-Player Blackjack Player Client (CS 457)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 client.py -i server.smith.edu -p 8080\n"
            "  python3 client.py -i 127.0.0.1 -p 8080\n"
            "  python3 client.py -h\n"
        ),
    )
    parser.add_argument(
        "-i", "--hostname",
        required=True,
        metavar="HOSTNAME",
        help="DNS hostname of the game server (resolved via socket.gethostbyname()).",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        required=True,
        metavar="PORT",
        help="TCP port the server is listening on.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main():
    """
    Entry point: parse args → resolve DNS → connect → join game → play loop.

    Flow:
        1. Parse -i and -p from command line.
        2. Resolve hostname with socket.gethostbyname(); exit(1) on gaierror.
        3. Open TCP connection to the server.
        4. Prompt for player name and balance; send CONNECT.
        5. Enter main_loop() to receive messages and play the game.
    """
    args = parse_args()

    if args.port < 1 or args.port > 65535:
        print("[ERROR] Port must be between 1 and 65535.", file=sys.stderr)
        sys.exit(1)

    # --- DNS Resolution (must use gaierror, must not crash) ---
    print(f"\n  Resolving '{args.hostname}'...")
    ip = resolve_host(args.hostname)
    print(f"  Resolved to {ip}")

    # --- TCP Connection ---
    print(f"  Connecting to {ip}:{args.port}...")
    sock = connect_to_server(ip, args.port)
    print(f"  Connected!\n")

    state = ClientState()

    # --- Collect player info from stdin ---
    try:
        name = input("  Enter your player name: ").strip() or "Player"
    except (EOFError, KeyboardInterrupt):
        sys.exit(0)

    while True:
        try:
            balance_raw = input("  Enter your starting balance (chips): ").strip()
            balance = int(balance_raw)
            if balance <= 0:
                print("  ✗ Balance must be a positive number.")
                continue
            break
        except ValueError:
            print("  ✗ Please enter a whole number.")
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)

    state.name    = name
    state.balance = balance

    # --- Send CONNECT ---
    # The client does not know its assigned player_id yet; the server
    # assigns one and reports it in the first LOBBY_WAIT response.
    # Send "unknown" as the placeholder — the server ignores the player_id
    # field on CONNECT messages and replaces it with the slot assignment.
    connect_msg = build_msg("CONNECT", "unknown", {
        "player_name": name,
        "balance":     balance,
    })
    send_msg(sock, connect_msg)

    # --- Receive LOBBY_WAITs until it is time to bet ---
    # The server sends at least one LOBBY_WAIT to assign our ID.
    # If we are Player 1 we also receive a second LOBBY_WAIT once Player 2
    # connects (current_players == 2).  We stay in this loop until the
    # server tells us both players are present, then we place our bet.
    buf = [""]
    print("  Waiting for server assignment...")
    while True:
        try:
            msg = recv_msg(sock, buf)
        except ConnectionError as exc:
            print(f"\n[ERROR] {exc}", file=sys.stderr)
            sys.exit(1)

        if msg is None:
            continue

        msg_type = msg.get("msg_type", "")

        if msg_type == "LOBBY_WAIT":
            payload  = msg.get("payload", {})
            assigned = payload.get("assigned_id")

            # Store our ID on the first LOBBY_WAIT that tells us our seat
            if assigned and state.player_id is None:
                state.player_id = assigned

            current  = payload.get("current_players", 1)
            required = payload.get("required_players", 2)
            render_lobby(payload, state.player_id)

            if current >= required:
                # Both seats filled — prompt for bet and move to game loop
                prompt_initial_bet(sock, state)
                break
            # else: still waiting for the other player; keep looping

        elif msg_type == "ERROR":
            handle_error(msg, state)
            sock.close()
            sys.exit(1)

        elif msg_type == "GAME_START":
            # Edge case: server sent GAME_START before we finished the lobby
            # loop (shouldn't happen, but handle it gracefully)
            handle_game_start(msg, state, sock)
            _maybe_take_turn(sock, state, buf)
            _main_loop_with_buf(sock, state, buf)
            return

        else:
            print(f"\n  [WARN] Unexpected message during lobby: {msg_type!r}")

    # --- Main game loop ---
    # Keeps reading from buf so we don't lose data already buffered
    _main_loop_with_buf(sock, state, buf)


def _main_loop_with_buf(sock, state, buf):
    """
    Variant of main_loop that accepts a pre-filled buffer.

    Used when some data may have already been read during the
    lobby/CONNECT handshake.

    Args:
        sock (socket.socket): Connected TCP socket.
        state (ClientState): Mutable client state object.
        buf (list): Pre-filled mutable string buffer.
    """
    while state.phase != ClientState.DONE:
        # Also watch for a second LOBBY_WAIT (player 2 just joined)
        # and prompt for bet if we haven't yet
        try:
            msg = recv_msg(sock, buf)
        except ConnectionError as exc:
            print(f"\n[ERROR] Lost connection to server: {exc}", file=sys.stderr)
            sys.exit(1)

        if msg is None:
            continue

        msg_type = msg.get("msg_type", "")

        if msg_type == "LOBBY_WAIT":
            payload  = msg.get("payload", {})
            current  = payload.get("current_players", 0)
            required = payload.get("required_players", 2)
            handle_lobby_wait(msg, state, sock)

            if current >= required and state.phase == ClientState.LOBBY_WAIT:
                prompt_initial_bet(sock, state)

        elif msg_type == "GAME_START":
            handle_game_start(msg, state, sock)
            _maybe_take_turn(sock, state, buf)

        elif msg_type == "STATE_UPDATE":
            handle_state_update(msg, state, sock)
            _maybe_take_turn(sock, state, buf)

        elif msg_type == "GAME_OVER":
            handle_game_over(msg, state, sock)

        elif msg_type == "ERROR":
            handle_error(msg, state)
            if state.phase == ClientState.MY_TURN:
                _maybe_take_turn(sock, state, buf)

        elif msg_type == "DISCONNECT":
            print("\n  The server has ended the session.")
            sys.exit(0)

        else:
            print(f"\n  [WARN] Unrecognised message type: {msg_type!r}")


if __name__ == "__main__":
    main()
