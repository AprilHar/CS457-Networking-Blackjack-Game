"""
test_blackjack.py — Unit Tests for server.py and client.py
CS 457 Networking — Sprint 2

Run with:
    python3 -m pytest test_blackjack.py -v
  or:
    python3 -m unittest discover

Coverage:
    - server.py : build_deck, hand_score, is_pair, card_label, build_msg,
                  frame_msg, validate_msg, PlayerSession, GameState FSM,
                  BlackjackServer (via mock sockets)
    - client.py : resolve_host, parse_args, send_msg, recv_msg, build_msg,
                  prompt_bet, prompt_move, card_label, render_board,
                  render_game_over, render_lobby, render_error,
                  _is_pair, handle_lobby_wait, handle_state_update,
                  handle_game_over, handle_error
"""

import io
import json
import socket
import sys
import time
import unittest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Import modules under test
# ---------------------------------------------------------------------------
import importlib.util, os

# Resolve absolute paths so tests run from any working directory
_BASE = os.path.dirname(os.path.abspath(__file__))


def _load(name, filename):
    """Dynamically load a module from a file path."""
    spec   = importlib.util.spec_from_file_location(name, os.path.join(_BASE, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = _load("server", "server.py")
client = _load("client", "client.py")


# ===========================================================================
# SERVER-SIDE TESTS
# ===========================================================================

class TestHandScore(unittest.TestCase):
    """Unit tests for server.hand_score()."""

    def test_empty_hand_returns_zero(self):
        self.assertEqual(server.hand_score([]), 0)

    def test_single_number_card(self):
        self.assertEqual(server.hand_score([{"rank": "7", "suit": "HEARTS"}]), 7)

    def test_face_cards_worth_ten(self):
        for rank in ("J", "Q", "K"):
            with self.subTest(rank=rank):
                self.assertEqual(
                    server.hand_score([{"rank": rank, "suit": "SPADES"}]), 10
                )

    def test_ace_counts_as_11_when_safe(self):
        cards = [{"rank": "A", "suit": "HEARTS"}, {"rank": "7", "suit": "CLUBS"}]
        self.assertEqual(server.hand_score(cards), 18)

    def test_ace_reduces_to_1_to_avoid_bust(self):
        cards = [
            {"rank": "A",  "suit": "HEARTS"},
            {"rank": "7",  "suit": "CLUBS"},
            {"rank": "8",  "suit": "SPADES"},
        ]
        self.assertEqual(server.hand_score(cards), 16)

    def test_two_aces_one_reduces(self):
        cards = [
            {"rank": "A", "suit": "HEARTS"},
            {"rank": "A", "suit": "SPADES"},
        ]
        self.assertEqual(server.hand_score(cards), 12)

    def test_blackjack_natural(self):
        cards = [
            {"rank": "A",  "suit": "HEARTS"},
            {"rank": "K",  "suit": "SPADES"},
        ]
        self.assertEqual(server.hand_score(cards), 21)

    def test_bust_score_above_21(self):
        cards = [
            {"rank": "10", "suit": "HEARTS"},
            {"rank": "7",  "suit": "CLUBS"},
            {"rank": "9",  "suit": "DIAMONDS"},
        ]
        self.assertEqual(server.hand_score(cards), 26)

    def test_ten_value_cards(self):
        cards = [
            {"rank": "10", "suit": "SPADES"},
            {"rank": "10", "suit": "HEARTS"},
        ]
        self.assertEqual(server.hand_score(cards), 20)

    def test_multiple_aces_all_reduce(self):
        # A + A + A + 9 = 11+1+1+9 = 22, reduce twice → 12
        cards = [
            {"rank": "A", "suit": "HEARTS"},
            {"rank": "A", "suit": "SPADES"},
            {"rank": "A", "suit": "CLUBS"},
            {"rank": "9", "suit": "DIAMONDS"},
        ]
        self.assertEqual(server.hand_score(cards), 12)


class TestBuildDeck(unittest.TestCase):
    """Unit tests for server.build_deck()."""

    def test_deck_has_52_cards(self):
        deck = server.build_deck()
        self.assertEqual(len(deck), 52)

    def test_all_suits_present(self):
        deck  = server.build_deck()
        suits = {c["suit"] for c in deck}
        self.assertEqual(suits, set(server.SUITS))

    def test_all_ranks_present(self):
        deck  = server.build_deck()
        ranks = {c["rank"] for c in deck}
        self.assertEqual(ranks, set(server.RANKS))

    def test_each_card_unique(self):
        deck  = server.build_deck()
        pairs = {(c["suit"], c["rank"]) for c in deck}
        self.assertEqual(len(pairs), 52)

    def test_deck_is_dict_list(self):
        deck = server.build_deck()
        for card in deck:
            self.assertIn("suit", card)
            self.assertIn("rank", card)

    def test_deck_is_shuffled(self):
        """Very unlikely (1/52!) that two shuffles produce identical order."""
        deck1 = server.build_deck()
        deck2 = server.build_deck()
        # Allow a tiny probability of false failure; in practice never equal
        self.assertNotEqual(
            [(c["suit"], c["rank"]) for c in deck1],
            [(c["suit"], c["rank"]) for c in deck2],
        )


class TestIsPair(unittest.TestCase):
    """Unit tests for server.is_pair()."""

    def test_matching_number_ranks(self):
        cards = [{"rank": "7", "suit": "HEARTS"}, {"rank": "7", "suit": "SPADES"}]
        self.assertTrue(server.is_pair(cards))

    def test_different_ranks_not_a_pair(self):
        cards = [{"rank": "7", "suit": "HEARTS"}, {"rank": "8", "suit": "SPADES"}]
        self.assertFalse(server.is_pair(cards))

    def test_face_cards_same_value_are_pair(self):
        # J and Q both worth 10 — counted as a pair for split purposes
        cards = [{"rank": "J", "suit": "HEARTS"}, {"rank": "Q", "suit": "SPADES"}]
        self.assertTrue(server.is_pair(cards))

    def test_three_cards_not_a_pair(self):
        cards = [
            {"rank": "7", "suit": "HEARTS"},
            {"rank": "7", "suit": "SPADES"},
            {"rank": "7", "suit": "CLUBS"},
        ]
        self.assertFalse(server.is_pair(cards))

    def test_one_card_not_a_pair(self):
        cards = [{"rank": "7", "suit": "HEARTS"}]
        self.assertFalse(server.is_pair(cards))

    def test_aces_are_a_pair(self):
        cards = [{"rank": "A", "suit": "HEARTS"}, {"rank": "A", "suit": "SPADES"}]
        self.assertTrue(server.is_pair(cards))


class TestCardLabel(unittest.TestCase):
    """Unit tests for server.card_label()."""

    def test_heart_ace(self):
        self.assertEqual(server.card_label({"rank": "A", "suit": "HEARTS"}), "A♥")

    def test_spade_ten(self):
        self.assertEqual(server.card_label({"rank": "10", "suit": "SPADES"}), "10♠")

    def test_diamond_king(self):
        self.assertEqual(server.card_label({"rank": "K", "suit": "DIAMONDS"}), "K♦")

    def test_club_two(self):
        self.assertEqual(server.card_label({"rank": "2", "suit": "CLUBS"}), "2♣")


class TestBuildMsg(unittest.TestCase):
    """Unit tests for server.build_msg()."""

    def test_valid_message_structure(self):
        msg = server.build_msg("CONNECT", {"player_name": "Alice"})
        self.assertEqual(msg["msg_type"],  "CONNECT")
        self.assertEqual(msg["player_id"], "dealer")
        self.assertIsInstance(msg["timestamp"], int)
        self.assertEqual(msg["payload"], {"player_name": "Alice"})

    def test_timestamp_is_recent(self):
        before = int(time.time())
        msg    = server.build_msg("ERROR", {})
        after  = int(time.time())
        self.assertGreaterEqual(msg["timestamp"], before)
        self.assertLessEqual(msg["timestamp"], after)

    def test_invalid_msg_type_raises(self):
        with self.assertRaises(ValueError):
            server.build_msg("BOGUS_TYPE", {})

    def test_all_valid_types_accepted(self):
        for t in server.VALID_MSG_TYPES:
            with self.subTest(msg_type=t):
                msg = server.build_msg(t, {})
                self.assertEqual(msg["msg_type"], t)

    def test_payload_preserved(self):
        payload = {"foo": 1, "bar": [1, 2, 3]}
        msg = server.build_msg("GAME_OVER", payload)
        self.assertEqual(msg["payload"], payload)


class TestFrameMsg(unittest.TestCase):
    """Unit tests for server.frame_msg()."""

    def test_ends_with_newline(self):
        msg   = server.build_msg("ERROR", {"error_code": "X", "message": "test"})
        framed = server.frame_msg(msg)
        self.assertTrue(framed.endswith(b"\n"))

    def test_is_valid_json_before_newline(self):
        msg    = server.build_msg("LOBBY_WAIT", {"message": "hi"})
        framed = server.frame_msg(msg)
        parsed = json.loads(framed.decode("utf-8").strip())
        self.assertEqual(parsed["msg_type"], "LOBBY_WAIT")

    def test_returns_bytes(self):
        msg    = server.build_msg("READY", {})
        framed = server.frame_msg(msg)
        self.assertIsInstance(framed, bytes)


class TestValidateMsg(unittest.TestCase):
    """Unit tests for server.validate_msg()."""

    def _make_raw(self, **overrides):
        base = {
            "msg_type":  "CONNECT",
            "player_id": "gambler_1",
            "timestamp": 123456,
            "payload":   {},
        }
        base.update(overrides)
        return json.dumps(base)

    def test_valid_message_passes(self):
        raw = self._make_raw()
        msg = server.validate_msg(raw)
        self.assertEqual(msg["msg_type"], "CONNECT")

    def test_missing_msg_type_raises(self):
        raw = json.dumps({"player_id": "gambler_1", "timestamp": 1, "payload": {}})
        with self.assertRaises(ValueError):
            server.validate_msg(raw)

    def test_missing_player_id_raises(self):
        raw = json.dumps({"msg_type": "CONNECT", "timestamp": 1, "payload": {}})
        with self.assertRaises(ValueError):
            server.validate_msg(raw)

    def test_missing_timestamp_raises(self):
        raw = json.dumps({"msg_type": "CONNECT", "player_id": "gambler_1", "payload": {}})
        with self.assertRaises(ValueError):
            server.validate_msg(raw)

    def test_missing_payload_raises(self):
        raw = json.dumps({"msg_type": "CONNECT", "player_id": "gambler_1", "timestamp": 1})
        with self.assertRaises(ValueError):
            server.validate_msg(raw)

    def test_bad_json_raises(self):
        with self.assertRaises(ValueError):
            server.validate_msg("{not valid json")

    def test_unknown_msg_type_raises(self):
        with self.assertRaises(ValueError):
            server.validate_msg(self._make_raw(msg_type="BOGUS"))

    def test_unknown_player_id_raises(self):
        with self.assertRaises(ValueError):
            server.validate_msg(self._make_raw(player_id="unknown_player"))

    def test_all_valid_player_ids_accepted(self):
        for pid in server.VALID_PLAYER_IDS:
            with self.subTest(player_id=pid):
                raw = self._make_raw(player_id=pid)
                msg = server.validate_msg(raw)
                self.assertEqual(msg["player_id"], pid)


class TestPlayerSession(unittest.TestCase):
    """Unit tests for server.PlayerSession."""

    def setUp(self):
        self.session = server.PlayerSession("gambler_1")

    def test_initial_state(self):
        s = self.session
        self.assertEqual(s.player_id, "gambler_1")
        self.assertEqual(s.balance,   0)
        self.assertFalse(s.connected)
        self.assertFalse(s.ready)
        self.assertEqual(s.hands, [])
        self.assertEqual(s.bet,   0)

    def test_make_hand_appends_to_hands(self):
        cards = [{"rank": "A", "suit": "HEARTS"}, {"rank": "K", "suit": "SPADES"}]
        hand  = self.session.make_hand(cards, 25)
        self.assertEqual(len(self.session.hands), 1)
        self.assertEqual(hand["score"], 21)
        self.assertEqual(hand["bet"],   25)
        self.assertEqual(hand["status"], server.STATUS_ACTIVE)

    def test_reset_round_clears_hand_and_bet(self):
        cards = [{"rank": "5", "suit": "CLUBS"}]
        self.session.make_hand(cards, 10)
        self.session.balance = 100
        self.session.reset_round()
        self.assertEqual(self.session.hands, [])
        self.assertEqual(self.session.bet,   0)
        self.assertFalse(self.session.ready)
        # Balance should NOT be reset
        self.assertEqual(self.session.balance, 100)

    def test_to_state_dict_structure(self):
        cards = [{"rank": "7", "suit": "HEARTS"}, {"rank": "8", "suit": "CLUBS"}]
        self.session.balance = 500
        self.session.make_hand(cards, 50)
        d = self.session.to_state_dict()
        self.assertEqual(d["player_id"], "gambler_1")
        self.assertEqual(d["balance"],   500)
        self.assertEqual(len(d["hands"]), 1)
        self.assertEqual(d["hands"][0]["score"], 15)


class TestGameStateFSM(unittest.TestCase):
    """Unit tests for server.GameState FSM transitions."""

    def setUp(self):
        self.gs = server.GameState()

    def test_initial_state_is_disconnected(self):
        self.assertEqual(self.gs.fsm_state, server.ServerFSM.DISCONNECTED)

    def test_valid_transition_player_connected(self):
        self.gs.transition("player_connected")
        self.assertEqual(self.gs.fsm_state, server.ServerFSM.WAITING_FOR_PLAYERS)

    def test_full_connection_path(self):
        self.gs.transition("player_connected")   # -> WAITING_FOR_PLAYERS
        self.gs.transition("player_connected")   # -> BETTING
        self.assertEqual(self.gs.fsm_state, server.ServerFSM.BETTING)

    def test_betting_to_dealing(self):
        self.gs.transition("player_connected")
        self.gs.transition("player_connected")
        self.gs.transition("wagers_ready")
        self.assertEqual(self.gs.fsm_state, server.ServerFSM.DEALING)

    def test_dealing_to_player_turn(self):
        self.gs.transition("player_connected")
        self.gs.transition("player_connected")
        self.gs.transition("wagers_ready")
        self.gs.transition("game_start")
        self.assertEqual(self.gs.fsm_state, server.ServerFSM.PLAYER_TURN)

    def test_illegal_transition_raises_value_error(self):
        # Can't go from DISCONNECTED to BETTING directly
        with self.assertRaises(ValueError):
            self.gs.transition("wagers_ready")

    def test_disconnect_from_waiting_to_cleanup(self):
        self.gs.transition("player_connected")   # -> WAITING_FOR_PLAYERS
        self.gs.transition("disconnect")          # -> CLEANUP
        self.assertEqual(self.gs.fsm_state, server.ServerFSM.CLEANUP)

    def test_cleanup_both_remain(self):
        # Navigate to CLEANUP
        for ev in ("player_connected", "player_connected", "wagers_ready",
                   "game_start", "turn_ends", "all_done", "dealer_resolves", "game_over"):
            self.gs.transition(ev)
        self.gs.transition("both_remain")
        self.assertEqual(self.gs.fsm_state, server.ServerFSM.BETTING)

    def test_cleanup_one_remains(self):
        for ev in ("player_connected", "player_connected", "wagers_ready",
                   "game_start", "turn_ends", "all_done", "dealer_resolves", "game_over"):
            self.gs.transition(ev)
        self.gs.transition("one_remains")
        self.assertEqual(self.gs.fsm_state, server.ServerFSM.WAITING_FOR_PLAYERS)

    def test_cleanup_none_remain(self):
        for ev in ("player_connected", "player_connected", "wagers_ready",
                   "game_start", "turn_ends", "all_done", "dealer_resolves", "game_over"):
            self.gs.transition(ev)
        self.gs.transition("none_remain")
        self.assertEqual(self.gs.fsm_state, server.ServerFSM.DISCONNECTED)

    def test_hit_or_split_stays_player_turn(self):
        for ev in ("player_connected", "player_connected",
                   "wagers_ready", "game_start"):
            self.gs.transition(ev)
        self.gs.transition("hit_or_split")
        self.assertEqual(self.gs.fsm_state, server.ServerFSM.PLAYER_TURN)


class TestGameStateDeck(unittest.TestCase):
    """Unit tests for server.GameState deck helpers."""

    def setUp(self):
        self.gs       = server.GameState()
        self.gs.deck  = server.build_deck()

    def test_deal_card_removes_from_deck(self):
        before = len(self.gs.deck)
        self.gs.deal_card()
        self.assertEqual(len(self.gs.deck), before - 1)

    def test_deal_card_returns_dict(self):
        card = self.gs.deal_card()
        self.assertIn("suit", card)
        self.assertIn("rank", card)

    def test_deal_card_refreshes_empty_deck(self):
        self.gs.deck = []  # Empty the deck
        card = self.gs.deal_card()
        self.assertIsNotNone(card)

    def test_all_players_done_when_all_stand(self):
        gs = self.gs
        for pid in server.PLAYER_IDS:
            p = gs.players[pid]
            p.connected = True
            p.make_hand([{"rank": "10", "suit": "HEARTS"}, {"rank": "8", "suit": "CLUBS"}], 25)
            p.hands[0]["status"] = server.STATUS_STAND
        self.assertTrue(gs.all_players_done())

    def test_all_players_done_false_when_active(self):
        gs = self.gs
        p  = gs.players["gambler_1"]
        p.connected = True
        p.make_hand([{"rank": "10", "suit": "HEARTS"}], 25)
        # status defaults to ACTIVE
        self.assertFalse(gs.all_players_done())


class TestBlackjackServerIntegration(unittest.TestCase):
    """
    Integration-style tests for BlackjackServer using mock sockets.

    We instantiate the server, manually inject mock sockets for players,
    and call the private handler methods directly to verify game logic
    without requiring a live network.
    """

    def _make_server(self):
        srv = server.BlackjackServer(0)  # Port 0 — not bound in tests
        return srv

    def _connect_player(self, srv, player_id, name="TestPlayer", balance=500):
        """Inject a connected player session with a mock socket."""
        mock_sock = MagicMock()
        mock_sock.fileno.return_value = hash(player_id) % 1000
        p = srv.game.players[player_id]
        p.sock      = mock_sock
        p.connected = True
        return mock_sock

    def _advance_to_betting(self, srv):
        """Helper: connect both players, advance FSM to BETTING."""
        srv.game.transition("player_connected")
        srv.game.transition("player_connected")
        for pid in server.PLAYER_IDS:
            p = srv.game.players[pid]
            p.connected = True
            p.name      = "Test"
            p.balance   = 500
            p.sock      = MagicMock()
            p.sock.fileno.return_value = hash(pid)

    # --- CONNECT ---

    def test_handle_connect_missing_fields_sends_error(self):
        srv = self._make_server()
        self._connect_player(srv, "gambler_1")
        with patch.object(srv, '_send_error') as mock_err:
            srv._handle_connect("gambler_1", {"player_name": "Alice"})  # missing balance
            mock_err.assert_called_once()
            self.assertEqual(mock_err.call_args[0][1], "INVALID_PAYLOAD")

    def test_handle_connect_negative_balance_sends_error(self):
        srv = self._make_server()
        self._connect_player(srv, "gambler_1")
        with patch.object(srv, '_send_error') as mock_err:
            srv._handle_connect("gambler_1", {"player_name": "Alice", "balance": -100})
            mock_err.assert_called_once()
            self.assertEqual(mock_err.call_args[0][1], "INVALID_BALANCE")

    def test_handle_connect_advances_fsm_on_first_player(self):
        srv = self._make_server()
        self._connect_player(srv, "gambler_1")
        with patch.object(srv, 'send_to'):
            srv._handle_connect("gambler_1", {"player_name": "Alice", "balance": 500})
        self.assertEqual(srv.game.fsm_state, server.ServerFSM.WAITING_FOR_PLAYERS)

    def test_handle_connect_advances_fsm_on_second_player(self):
        srv = self._make_server()
        for pid in server.PLAYER_IDS:
            self._connect_player(srv, pid)
        with patch.object(srv, 'send_to'):
            srv._handle_connect("gambler_1", {"player_name": "Alice", "balance": 500})
            srv._handle_connect("gambler_2", {"player_name": "Bob", "balance": 500})
        self.assertEqual(srv.game.fsm_state, server.ServerFSM.BETTING)

    # --- READY ---

    def test_handle_ready_wrong_state_sends_error(self):
        srv = self._make_server()
        self._connect_player(srv, "gambler_1")
        # FSM is DISCONNECTED — not BETTING
        with patch.object(srv, '_send_error') as mock_err:
            srv._handle_ready("gambler_1", {"bet_amount": 25, "ready_status": True})
            mock_err.assert_called_once()
            self.assertEqual(mock_err.call_args[0][1], "WRONG_STATE")

    def test_handle_ready_invalid_bet_zero(self):
        srv = self._make_server()
        self._advance_to_betting(srv)
        with patch.object(srv, '_send_error') as mock_err:
            srv._handle_ready("gambler_1", {"bet_amount": 0, "ready_status": True})
            mock_err.assert_called_once()
            self.assertEqual(mock_err.call_args[0][1], "INVALID_BET")

    def test_handle_ready_bet_exceeds_balance_sends_error(self):
        srv = self._make_server()
        self._advance_to_betting(srv)
        with patch.object(srv, '_send_error') as mock_err:
            srv._handle_ready("gambler_1", {"bet_amount": 9999, "ready_status": True})
            mock_err.assert_called_once()
            self.assertEqual(mock_err.call_args[0][1], "INSUFFICIENT_BALANCE")

    def test_handle_ready_records_bet(self):
        srv = self._make_server()
        self._advance_to_betting(srv)
        with patch.object(srv, '_send_error'), patch.object(srv, '_start_round'):
            srv._handle_ready("gambler_1", {"bet_amount": 50, "ready_status": True})
        self.assertEqual(srv.game.players["gambler_1"].bet, 50)
        self.assertTrue(srv.game.players["gambler_1"].ready)

    def test_handle_ready_both_ready_calls_start_round(self):
        srv = self._make_server()
        self._advance_to_betting(srv)
        with patch.object(srv, '_start_round') as mock_start, \
             patch.object(srv, '_send_error'):
            srv._handle_ready("gambler_1", {"bet_amount": 25, "ready_status": True})
            srv._handle_ready("gambler_2", {"bet_amount": 50, "ready_status": True})
            mock_start.assert_called_once()

    # --- MOVE ---

    def test_handle_move_wrong_state_sends_error(self):
        srv = self._make_server()
        self._connect_player(srv, "gambler_1")
        with patch.object(srv, '_send_error') as mock_err:
            srv._handle_move("gambler_1", {"action": "HIT", "hand_index": 0})
            mock_err.assert_called_once()
            self.assertEqual(mock_err.call_args[0][1], "WRONG_STATE")

    def test_handle_move_not_your_turn_sends_error(self):
        srv = self._make_server()
        self._advance_to_betting(srv)
        # Manually put FSM in PLAYER_TURN and assign turn to gambler_1
        for _ in range(2):
            try:
                srv.game.transition("wagers_ready")
                srv.game.transition("game_start")
            except ValueError:
                break
        # Force state
        srv.game.fsm_state    = server.ServerFSM.PLAYER_TURN
        srv.game.current_turn = "gambler_1"

        with patch.object(srv, '_send_error') as mock_err:
            srv._handle_move("gambler_2", {"action": "HIT", "hand_index": 0})
            mock_err.assert_called_once()
            self.assertEqual(mock_err.call_args[0][1], "NOT_YOUR_TURN")

    def test_handle_move_invalid_action_sends_error(self):
        srv = self._make_server()
        srv.game.fsm_state    = server.ServerFSM.PLAYER_TURN
        srv.game.current_turn = "gambler_1"
        self._connect_player(srv, "gambler_1")
        srv.game.players["gambler_1"].make_hand(
            [{"rank": "5", "suit": "HEARTS"}, {"rank": "6", "suit": "CLUBS"}], 25
        )
        with patch.object(srv, '_send_error') as mock_err:
            srv._handle_move("gambler_1", {"action": "FOLD", "hand_index": 0})
            mock_err.assert_called_once()
            self.assertEqual(mock_err.call_args[0][1], "INVALID_ACTION")

    def test_handle_move_invalid_hand_index_sends_error(self):
        srv = self._make_server()
        srv.game.fsm_state    = server.ServerFSM.PLAYER_TURN
        srv.game.current_turn = "gambler_1"
        self._connect_player(srv, "gambler_1")
        srv.game.players["gambler_1"].make_hand(
            [{"rank": "5", "suit": "HEARTS"}, {"rank": "6", "suit": "CLUBS"}], 25
        )
        with patch.object(srv, '_send_error') as mock_err:
            srv._handle_move("gambler_1", {"action": "HIT", "hand_index": 5})
            mock_err.assert_called_once()
            self.assertEqual(mock_err.call_args[0][1], "INVALID_HAND_INDEX")

    # --- do_hit ---

    def _setup_player_turn(self, srv, player_id, cards, bet=25):
        """Helper: put server in PLAYER_TURN with a known hand."""
        srv.game.fsm_state    = server.ServerFSM.PLAYER_TURN
        srv.game.current_turn = player_id
        p = srv.game.players[player_id]
        p.connected = True
        p.balance   = 500
        p.name      = "Test"
        p.bet       = bet
        p.sock      = MagicMock()
        p.make_hand(cards, bet)
        # Also set up the other player so broadcasts don't fail
        other = "gambler_2" if player_id == "gambler_1" else "gambler_1"
        srv.game.players[other].connected = True
        srv.game.players[other].sock      = MagicMock()

    def test_do_hit_adds_card(self):
        srv = self._make_server()
        self._setup_player_turn(
            srv, "gambler_1",
            [{"rank": "5", "suit": "HEARTS"}, {"rank": "6", "suit": "CLUBS"}]
        )
        srv.game.deck = [{"rank": "3", "suit": "SPADES"}]
        with patch.object(srv, 'broadcast'), patch.object(srv, '_advance_turn'):
            srv._do_hit("gambler_1", 0)
        hand = srv.game.players["gambler_1"].hands[0]
        self.assertEqual(len(hand["cards"]), 3)
        self.assertEqual(hand["score"], 14)

    def test_do_hit_bust_marks_busted(self):
        srv = self._make_server()
        self._setup_player_turn(
            srv, "gambler_1",
            [{"rank": "10", "suit": "HEARTS"}, {"rank": "7", "suit": "CLUBS"}]
        )
        srv.game.deck = [{"rank": "9", "suit": "SPADES"}]
        with patch.object(srv, 'broadcast'), patch.object(srv, '_advance_turn'):
            srv._do_hit("gambler_1", 0)
        hand = srv.game.players["gambler_1"].hands[0]
        self.assertEqual(hand["status"], server.STATUS_BUSTED)

    def test_do_hit_bust_calls_advance_turn(self):
        srv = self._make_server()
        self._setup_player_turn(
            srv, "gambler_1",
            [{"rank": "10", "suit": "HEARTS"}, {"rank": "7", "suit": "CLUBS"}]
        )
        srv.game.deck = [{"rank": "9", "suit": "SPADES"}]
        with patch.object(srv, 'broadcast'), \
             patch.object(srv, '_advance_turn') as mock_adv:
            srv._do_hit("gambler_1", 0)
            mock_adv.assert_called_once()
            self.assertEqual(mock_adv.call_args[0][0], "gambler_1")

    # --- do_stand ---

    def test_do_stand_marks_hand_stand(self):
        srv = self._make_server()
        self._setup_player_turn(
            srv, "gambler_1",
            [{"rank": "10", "suit": "HEARTS"}, {"rank": "8", "suit": "CLUBS"}]
        )
        with patch.object(srv, 'broadcast'), patch.object(srv, '_advance_turn'):
            srv._do_stand("gambler_1", 0)
        hand = srv.game.players["gambler_1"].hands[0]
        self.assertEqual(hand["status"], server.STATUS_STAND)

    def test_do_stand_calls_advance_turn(self):
        srv = self._make_server()
        self._setup_player_turn(
            srv, "gambler_1",
            [{"rank": "10", "suit": "HEARTS"}, {"rank": "8", "suit": "CLUBS"}]
        )
        with patch.object(srv, 'broadcast'), \
             patch.object(srv, '_advance_turn') as mock_adv:
            srv._do_stand("gambler_1", 0)
            mock_adv.assert_called_once()
            self.assertEqual(mock_adv.call_args[0][0], "gambler_1")

    # --- do_double ---

    def test_do_double_requires_two_cards(self):
        srv = self._make_server()
        self._setup_player_turn(
            srv, "gambler_1",
            [{"rank": "5", "suit": "HEARTS"},
             {"rank": "5", "suit": "CLUBS"},
             {"rank": "5", "suit": "DIAMONDS"}]  # 3 cards
        )
        with patch.object(srv, '_send_error') as mock_err, \
             patch.object(srv, 'broadcast'):
            srv._do_double("gambler_1", 0)
            mock_err.assert_called_once()
            self.assertEqual(mock_err.call_args[0][1], "INVALID_MOVE")

    def test_do_double_insufficient_balance(self):
        srv = self._make_server()
        self._setup_player_turn(
            srv, "gambler_1",
            [{"rank": "5", "suit": "HEARTS"}, {"rank": "6", "suit": "CLUBS"}],
            bet=300,
        )
        srv.game.players["gambler_1"].balance = 50  # less than bet of 300
        with patch.object(srv, '_send_error') as mock_err, \
             patch.object(srv, 'broadcast'):
            srv._do_double("gambler_1", 0)
            mock_err.assert_called_once()
            self.assertEqual(mock_err.call_args[0][1], "INSUFFICIENT_BALANCE")

    def test_do_double_doubles_bet_and_deals_one_card(self):
        srv = self._make_server()
        self._setup_player_turn(
            srv, "gambler_1",
            [{"rank": "5", "suit": "HEARTS"}, {"rank": "6", "suit": "CLUBS"}],
            bet=50,
        )
        srv.game.players["gambler_1"].balance = 500
        srv.game.deck = [{"rank": "9", "suit": "DIAMONDS"}]
        with patch.object(srv, 'broadcast'), patch.object(srv, '_advance_turn'):
            srv._do_double("gambler_1", 0)
        hand = srv.game.players["gambler_1"].hands[0]
        self.assertEqual(hand["bet"],         100)   # doubled
        self.assertEqual(len(hand["cards"]),  3)     # exactly one new card
        self.assertIn(hand["status"], (server.STATUS_STAND, server.STATUS_BUSTED))
        self.assertEqual(srv.game.players["gambler_1"].bet, 100)
        self.assertEqual(srv.game.players["gambler_1"].to_state_dict()["bet"], 100)

    # --- do_split ---

    def test_do_split_requires_pair(self):
        srv = self._make_server()
        self._setup_player_turn(
            srv, "gambler_1",
            [{"rank": "5", "suit": "HEARTS"}, {"rank": "7", "suit": "CLUBS"}]
        )
        with patch.object(srv, '_send_error') as mock_err, \
             patch.object(srv, 'broadcast'):
            srv._do_split("gambler_1", 0)
            mock_err.assert_called_once()
            self.assertEqual(mock_err.call_args[0][1], "INVALID_MOVE")

    def test_do_split_insufficient_balance(self):
        srv = self._make_server()
        self._setup_player_turn(
            srv, "gambler_1",
            [{"rank": "7", "suit": "HEARTS"}, {"rank": "7", "suit": "CLUBS"}],
            bet=300,
        )
        srv.game.players["gambler_1"].balance = 50
        with patch.object(srv, '_send_error') as mock_err, \
             patch.object(srv, 'broadcast'):
            srv._do_split("gambler_1", 0)
            mock_err.assert_called_once()
            self.assertEqual(mock_err.call_args[0][1], "INSUFFICIENT_BALANCE")

    def test_do_split_creates_two_hands(self):
        srv = self._make_server()
        self._setup_player_turn(
            srv, "gambler_1",
            [{"rank": "7", "suit": "HEARTS"}, {"rank": "7", "suit": "CLUBS"}],
            bet=50,
        )
        srv.game.players["gambler_1"].balance = 500
        srv.game.deck = [{"rank": "3", "suit": "SPADES"}, {"rank": "4", "suit": "DIAMONDS"}]
        with patch.object(srv, 'broadcast'):
            srv._do_split("gambler_1", 0)
        p = srv.game.players["gambler_1"]
        self.assertEqual(len(p.hands), 2)
        for h in p.hands:
            self.assertEqual(len(h["cards"]), 2)
            self.assertEqual(h["bet"], 50)
        self.assertEqual(p.bet, 100)
        self.assertEqual(p.to_state_dict()["bet"], 100)

    # --- resolve_round ---

    def _setup_round_resolution(self, dealer_cards, p1_cards, p1_status,
                                 p2_cards, p2_status, bet=25):
        """Helper: set up game state for resolve_round tests."""
        srv = self._make_server()
        srv.game.fsm_state = server.ServerFSM.ROUND_END

        srv.game.dealer_hand  = dealer_cards
        srv.game.dealer_score = server.hand_score(dealer_cards)

        for pid, cards, status in [
            ("gambler_1", p1_cards, p1_status),
            ("gambler_2", p2_cards, p2_status),
        ]:
            p = srv.game.players[pid]
            p.connected = True
            p.balance   = 500 - bet
            p.sock      = MagicMock()
            hand = {
                "cards":  cards,
                "score":  server.hand_score(cards),
                "bet":    bet,
                "status": status,
            }
            p.hands = [hand]

        return srv

    def test_resolve_round_player_wins_dealer_busts(self):
        dealer = [{"rank": "10", "suit": "H"}, {"rank": "7", "suit": "D"}, {"rank": "9", "suit": "C"}]
        p1_cards = [{"rank": "10", "suit": "S"}, {"rank": "8", "suit": "H"}]  # 18, stand
        p2_cards = [{"rank": "5",  "suit": "C"}, {"rank": "6", "suit": "D"}]  # 11, stand
        srv = self._setup_round_resolution(
            dealer, p1_cards, server.STATUS_STAND, p2_cards, server.STATUS_STAND
        )
        with patch.object(srv, 'broadcast'), patch.object(srv, '_cleanup'):
            srv._resolve_round()
        # Both players should have won (dealer busted with 26)
        p1 = srv.game.players["gambler_1"]
        self.assertGreater(p1.balance, 475)  # started at 475 (500-25); won 50 back

    def test_resolve_round_player_busted_loses(self):
        dealer = [{"rank": "10", "suit": "H"}, {"rank": "7", "suit": "D"}]  # 17
        p1_cards = [
            {"rank": "10", "suit": "S"},
            {"rank": "7",  "suit": "H"},
            {"rank": "9",  "suit": "C"},
        ]  # 26, busted
        p2_cards = [{"rank": "5", "suit": "C"}, {"rank": "6", "suit": "D"}]  # 11
        srv = self._setup_round_resolution(
            dealer,
            p1_cards, server.STATUS_BUSTED,
            p2_cards, server.STATUS_STAND,
        )
        with patch.object(srv, 'broadcast'), patch.object(srv, '_cleanup'):
            srv._resolve_round()
        # Gambler 1 busted — should not receive payout
        p1 = srv.game.players["gambler_1"]
        self.assertEqual(p1.balance, 475)  # 500 - 25, no payout

    def test_resolve_round_push_returns_bet(self):
        dealer = [{"rank": "10", "suit": "H"}, {"rank": "7", "suit": "D"}]  # 17
        p1_cards = [{"rank": "10", "suit": "S"}, {"rank": "7", "suit": "C"}]  # 17, push
        p2_cards = [{"rank": "5",  "suit": "C"}, {"rank": "6", "suit": "D"}]  # 11
        srv = self._setup_round_resolution(
            dealer, p1_cards, server.STATUS_STAND, p2_cards, server.STATUS_STAND
        )
        with patch.object(srv, 'broadcast'), patch.object(srv, '_cleanup'):
            srv._resolve_round()
        p1 = srv.game.players["gambler_1"]
        self.assertEqual(p1.balance, 500)  # 475 + 25 (bet returned)

    def test_resolve_round_blackjack_pays_3_to_2(self):
        dealer = [{"rank": "10", "suit": "H"}, {"rank": "7", "suit": "D"}]  # 17
        p1_cards = [{"rank": "A", "suit": "S"}, {"rank": "K", "suit": "C"}]  # BJ=21
        p2_cards = [{"rank": "5", "suit": "C"}, {"rank": "6", "suit": "D"}]
        srv = self._setup_round_resolution(
            dealer, p1_cards, server.STATUS_ACTIVE,  # ACTIVE so is_blackjack triggers
            p2_cards, server.STATUS_STAND
        )
        srv.game.players["gambler_1"].hands[0]["status"] = server.STATUS_ACTIVE
        with patch.object(srv, 'broadcast'), patch.object(srv, '_cleanup'):
            srv._resolve_round()
        p1 = srv.game.players["gambler_1"]
        # 3:2 on 25 bet: payout = int(25 * 2.5) = 62; balance = 475 + 62 = 537
        self.assertEqual(p1.balance, 537)


# ===========================================================================
# CLIENT-SIDE TESTS
# ===========================================================================

class TestClientResolveHost(unittest.TestCase):
    """Unit tests for client.resolve_host()."""

    def test_valid_hostname_returns_ip(self):
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            ip = client.resolve_host("localhost")
        self.assertEqual(ip, "127.0.0.1")

    def test_gaierror_exits_with_code_1(self):
        with patch("socket.gethostbyname", side_effect=socket.gaierror(8, "Name or service not known")):
            with self.assertRaises(SystemExit) as ctx:
                client.resolve_host("nonexistent.invalid")
        self.assertEqual(ctx.exception.code, 1)

    def test_gaierror_prints_user_friendly_message(self):
        with patch("socket.gethostbyname", side_effect=socket.gaierror(8, "Name not known")):
            with self.assertRaises(SystemExit):
                with patch("sys.stderr", new_callable=io.StringIO) as mock_err:
                    try:
                        client.resolve_host("bad.hostname.invalid")
                    except SystemExit:
                        output = mock_err.getvalue()
                        self.assertIn("DNS", output.upper() if "DNS" not in output else output)
                        raise

    def test_no_unhandled_exception_on_dns_failure(self):
        """resolve_host must never let an unhandled exception propagate."""
        with patch("socket.gethostbyname", side_effect=socket.gaierror(1, "failure")):
            try:
                client.resolve_host("fail.invalid")
                self.fail("Expected SystemExit")
            except SystemExit:
                pass  # Correct — clean exit, no traceback
            except Exception as exc:
                self.fail(f"Unexpected exception leaked: {exc}")


class TestClientParseArgs(unittest.TestCase):
    """Unit tests for client.parse_args()."""

    def test_valid_args_parsed(self):
        with patch("sys.argv", ["client.py", "-i", "server.smith.edu", "-p", "8080"]):
            args = client.parse_args()
        self.assertEqual(args.hostname, "server.smith.edu")
        self.assertEqual(args.port,     8080)

    def test_missing_hostname_exits(self):
        with patch("sys.argv", ["client.py", "-p", "8080"]):
            with self.assertRaises(SystemExit):
                client.parse_args()

    def test_missing_port_exits(self):
        with patch("sys.argv", ["client.py", "-i", "server.smith.edu"]):
            with self.assertRaises(SystemExit):
                client.parse_args()

    def test_help_flag_exits_zero(self):
        with patch("sys.argv", ["client.py", "-h"]):
            with self.assertRaises(SystemExit) as ctx:
                client.parse_args()
        self.assertEqual(ctx.exception.code, 0)


class TestClientSendMsg(unittest.TestCase):
    """Unit tests for client.send_msg()."""

    def test_message_sent_as_json_newline(self):
        mock_sock = MagicMock()
        msg = {"msg_type": "CONNECT", "player_id": "gambler_1",
               "timestamp": 1, "payload": {}}
        client.send_msg(mock_sock, msg)
        sent = mock_sock.sendall.call_args[0][0]
        self.assertIsInstance(sent, bytes)
        self.assertTrue(sent.endswith(b"\n"))
        parsed = json.loads(sent.decode("utf-8").strip())
        self.assertEqual(parsed["msg_type"], "CONNECT")

    def test_all_fields_preserved(self):
        mock_sock = MagicMock()
        payload = {"bet_amount": 50, "ready_status": True}
        msg = {"msg_type": "READY", "player_id": "gambler_2",
               "timestamp": 999, "payload": payload}
        client.send_msg(mock_sock, msg)
        sent   = mock_sock.sendall.call_args[0][0]
        parsed = json.loads(sent.decode("utf-8").strip())
        self.assertEqual(parsed["payload"], payload)


class TestClientRecvMsg(unittest.TestCase):
    """Unit tests for client.recv_msg()."""

    def _mock_sock(self, data_bytes):
        sock = MagicMock()
        sock.recv.return_value = data_bytes
        return sock

    def test_complete_message_returned(self):
        msg    = {"msg_type": "LOBBY_WAIT", "player_id": "dealer",
                  "timestamp": 1, "payload": {}}
        data   = (json.dumps(msg) + "\n").encode("utf-8")
        sock   = self._mock_sock(data)
        buf    = [""]
        result = client.recv_msg(sock, buf)
        self.assertIsNotNone(result)
        self.assertEqual(result["msg_type"], "LOBBY_WAIT")

    def test_partial_data_returns_none(self):
        sock   = self._mock_sock(b'{"msg_type": "CONNECT"')
        buf    = [""]
        result = client.recv_msg(sock, buf)
        self.assertIsNone(result)
        # Partial data should be buffered
        self.assertIn("CONNECT", buf[0])

    def test_multiple_messages_in_buffer(self):
        msg1 = json.dumps({"msg_type": "LOBBY_WAIT", "player_id": "dealer",
                            "timestamp": 1, "payload": {}}) + "\n"
        msg2 = json.dumps({"msg_type": "GAME_START", "player_id": "dealer",
                            "timestamp": 2, "payload": {}}) + "\n"
        sock = MagicMock()
        sock.recv.return_value = (msg1 + msg2).encode("utf-8")
        buf = [""]
        r1  = client.recv_msg(sock, buf)
        self.assertEqual(r1["msg_type"], "LOBBY_WAIT")

        # Second call must drain msg2 from buffer WITHOUT calling sock.recv again
        sock.recv.side_effect = AssertionError("sock.recv called while buffer had data")
        r2 = client.recv_msg(sock, buf)
        self.assertEqual(r2["msg_type"], "GAME_START")

    def test_empty_recv_raises_connection_error(self):
        sock = self._mock_sock(b"")
        buf  = [""]
        with self.assertRaises(ConnectionError):
            client.recv_msg(sock, buf)

    def test_oserror_raises_connection_error(self):
        sock = MagicMock()
        sock.recv.side_effect = OSError("connection reset")
        buf  = [""]
        with self.assertRaises(ConnectionError):
            client.recv_msg(sock, buf)


class TestClientBuildMsg(unittest.TestCase):
    """Unit tests for client.build_msg()."""

    def test_envelope_structure(self):
        msg = client.build_msg("CONNECT", "gambler_1", {"player_name": "Alice", "balance": 500})
        self.assertEqual(msg["msg_type"],  "CONNECT")
        self.assertEqual(msg["player_id"], "gambler_1")
        self.assertIsInstance(msg["timestamp"], int)
        self.assertEqual(msg["payload"]["player_name"], "Alice")

    def test_timestamp_is_current(self):
        before = int(time.time())
        msg    = client.build_msg("MOVE", "gambler_2", {"action": "HIT", "hand_index": 0})
        after  = int(time.time())
        self.assertGreaterEqual(msg["timestamp"], before)
        self.assertLessEqual(msg["timestamp"],    after)


class TestClientPromptBet(unittest.TestCase):
    """Unit tests for client.prompt_bet()."""

    def test_valid_bet_accepted(self):
        with patch("builtins.input", return_value="50"):
            bet = client.prompt_bet(500)
        self.assertEqual(bet, 50)

    def test_bet_equal_to_balance_accepted(self):
        with patch("builtins.input", return_value="500"):
            bet = client.prompt_bet(500)
        self.assertEqual(bet, 500)

    def test_zero_bet_rejected_then_accepted(self):
        with patch("builtins.input", side_effect=["0", "25"]):
            bet = client.prompt_bet(500)
        self.assertEqual(bet, 25)

    def test_negative_bet_rejected_then_accepted(self):
        with patch("builtins.input", side_effect=["-10", "10"]):
            bet = client.prompt_bet(500)
        self.assertEqual(bet, 10)

    def test_bet_over_balance_rejected_then_accepted(self):
        with patch("builtins.input", side_effect=["9999", "100"]):
            bet = client.prompt_bet(100)
        self.assertEqual(bet, 100)

    def test_non_integer_rejected_then_accepted(self):
        with patch("builtins.input", side_effect=["abc", "30"]):
            bet = client.prompt_bet(500)
        self.assertEqual(bet, 30)


class TestClientHandScore(unittest.TestCase):
    """Unit tests for client.hand_score()."""

    def test_empty_hand(self):
        self.assertEqual(client.hand_score([]), 0)

    def test_blackjack_natural(self):
        self.assertEqual(
            client.hand_score([{"rank": "A", "suit": "S"}, {"rank": "K", "suit": "H"}]), 21
        )

    def test_soft_ace_reduction(self):
        self.assertEqual(
            client.hand_score([
                {"rank": "A", "suit": "S"},
                {"rank": "9", "suit": "H"},
                {"rank": "5", "suit": "D"},
            ]), 15
        )


class TestClientPromptMove(unittest.TestCase):
    """Unit tests for client.prompt_move()."""

    def _cards(self, *ranks):
        return [{"rank": r, "suit": "HEARTS"} for r in ranks]

    def test_hit_accepted(self):
        with patch("builtins.input", return_value="HIT"):
            action = client.prompt_move(self._cards("5", "6"), 11, False, False)
        self.assertEqual(action, "HIT")

    def test_stand_accepted(self):
        with patch("builtins.input", return_value="STAND"):
            action = client.prompt_move(self._cards("10", "8"), 18, False, False)
        self.assertEqual(action, "STAND")

    def test_double_accepted_when_allowed(self):
        with patch("builtins.input", return_value="DOUBLE"):
            action = client.prompt_move(self._cards("5", "6"), 11, True, False)
        self.assertEqual(action, "DOUBLE")

    def test_double_not_in_options_when_not_allowed(self):
        with patch("builtins.input", side_effect=["DOUBLE", "HIT"]):
            action = client.prompt_move(self._cards("5", "6"), 11, False, False)
        self.assertEqual(action, "HIT")

    def test_split_accepted_when_allowed(self):
        with patch("builtins.input", return_value="SPLIT"):
            action = client.prompt_move(self._cards("7", "7"), 14, False, True)
        self.assertEqual(action, "SPLIT")

    def test_invalid_input_re_prompts(self):
        with patch("builtins.input", side_effect=["FOLD", "STAND"]):
            action = client.prompt_move(self._cards("10", "8"), 18, False, False)
        self.assertEqual(action, "STAND")

    def test_case_insensitive(self):
        with patch("builtins.input", return_value="hit"):
            action = client.prompt_move(self._cards("5", "6"), 11, False, False)
        self.assertEqual(action, "HIT")

    def test_maybe_take_turn_prompts_on_game_start_payload(self):
        """_maybe_take_turn must properly parse single 'hand' in GAME_START and prompt."""
        state = client.ClientState()
        state.phase = client.ClientState.MY_TURN
        state.player_id = "gambler_1"
        state.last_state = {
            "current_turn": "gambler_1",
            "players": [
                {
                    "player_id": "gambler_1",
                    "bet": 25,
                    "hand": [{"rank": "10", "suit": "S"}, {"rank": "8", "suit": "H"}],
                }
            ],
        }
        mock_sock = MagicMock()
        buf = [""]

        # Simulate user choosing STAND, followed by server response STATE_UPDATE where turn changes
        stand_response = (
            json.dumps({
                "msg_type": "STATE_UPDATE",
                "player_id": "dealer",
                "timestamp": 1234,
                "payload": {
                    "current_turn": "gambler_2",
                    "players": [
                        {
                            "player_id": "gambler_1",
                            "balance": 475,
                            "hands": [{
                                "cards": [{"rank": "10", "suit": "S"}, {"rank": "8", "suit": "H"}],
                                "score": 18,
                                "bet": 25,
                                "status": "STAND",
                            }],
                        }
                    ],
                },
            }) + "\n"
        ).encode("utf-8")

        mock_sock.recv.return_value = stand_response

        with patch("builtins.input", return_value="STAND"), \
             patch("sys.stdout", new_callable=io.StringIO):
            client._maybe_take_turn(mock_sock, state, buf)

        # Confirm MOVE was sent over socket
        sent = mock_sock.sendall.call_args[0][0]
        parsed = json.loads(sent.decode("utf-8").strip())
        self.assertEqual(parsed["msg_type"], "MOVE")
        self.assertEqual(parsed["payload"]["action"], "STAND")
        # After stand and state update to gambler_2, state.phase must be WAITING
        self.assertEqual(state.phase, client.ClientState.WAITING)


class TestClientCardLabel(unittest.TestCase):
    """Unit tests for client.card_label()."""

    def test_ace_of_hearts(self):
        self.assertEqual(client.card_label({"rank": "A", "suit": "HEARTS"}), "A♥")

    def test_ten_of_spades(self):
        self.assertEqual(client.card_label({"rank": "10", "suit": "SPADES"}), "10♠")

    def test_none_returns_placeholder(self):
        self.assertEqual(client.card_label(None), "[??]")

    def test_king_of_diamonds(self):
        self.assertEqual(client.card_label({"rank": "K", "suit": "DIAMONDS"}), "K♦")


class TestClientIsPair(unittest.TestCase):
    """Unit tests for client._is_pair()."""

    def test_matching_ranks(self):
        cards = [{"rank": "7", "suit": "HEARTS"}, {"rank": "7", "suit": "SPADES"}]
        self.assertTrue(client._is_pair(cards))

    def test_non_matching_ranks(self):
        cards = [{"rank": "7", "suit": "HEARTS"}, {"rank": "8", "suit": "SPADES"}]
        self.assertFalse(client._is_pair(cards))

    def test_face_cards_same_value(self):
        cards = [{"rank": "J", "suit": "HEARTS"}, {"rank": "Q", "suit": "SPADES"}]
        self.assertTrue(client._is_pair(cards))

    def test_three_cards_not_pair(self):
        cards = [
            {"rank": "7", "suit": "HEARTS"},
            {"rank": "7", "suit": "SPADES"},
            {"rank": "7", "suit": "CLUBS"},
        ]
        self.assertFalse(client._is_pair(cards))


class TestClientRenderBoard(unittest.TestCase):
    """Smoke tests that render_board doesn't crash on well-formed payloads."""

    def _make_state_payload(self):
        return {
            "last_action":  None,
            "dealer": {
                "up_card": {"rank": "10", "suit": "HEARTS"},
                "score":   10,
                "cards":   [{"rank": "10", "suit": "HEARTS"}],
            },
            "players": [
                {
                    "player_id": "gambler_1",
                    "balance":   475,
                    "hands": [{
                        "cards":  [{"rank": "A", "suit": "SPADES"},
                                   {"rank": "5", "suit": "CLUBS"}],
                        "score":  16,
                        "bet":    25,
                        "status": "ACTIVE",
                    }],
                },
                {
                    "player_id": "gambler_2",
                    "balance":   450,
                    "hands": [{
                        "cards":  [{"rank": "8", "suit": "DIAMONDS"},
                                   {"rank": "7", "suit": "HEARTS"}],
                        "score":  15,
                        "bet":    50,
                        "status": "ACTIVE",
                    }],
                },
            ],
            "current_turn": "gambler_1",
        }

    def test_render_board_does_not_crash(self):
        payload = self._make_state_payload()
        with patch("sys.stdout", new_callable=io.StringIO):
            try:
                client.render_board(payload, "gambler_1")
            except Exception as exc:
                self.fail(f"render_board raised {exc}")

    def test_render_board_shows_dealer(self):
        payload = self._make_state_payload()
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            client.render_board(payload, "gambler_1")
            output = mock_out.getvalue()
        self.assertIn("DEALER", output)

    def test_render_board_shows_dealer_up_card_from_game_start(self):
        """GAME_START provides 'dealer_up_card' directly at the root."""
        payload = {
            "dealer_up_card": {"rank": "K", "suit": "HEARTS"},
            "players": [
                {
                    "player_id": "gambler_1",
                    "bet": 25,
                    "hand": [{"rank": "10", "suit": "S"}, {"rank": "8", "suit": "H"}],
                }
            ],
            "current_turn": "gambler_1",
        }
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            client.render_board(payload, "gambler_1")
            output = mock_out.getvalue()
        self.assertIn("K♥", output)
        self.assertIn("[??]", output)
        self.assertIn("Score: 10", output)

    def test_render_board_shows_bet_and_balance(self):
        """Player row must show their balance and current bet placed."""
        payload = self._make_state_payload()
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            client.render_board(payload, "gambler_1")
            output = mock_out.getvalue()
        self.assertIn("Balance: $475", output)
        self.assertIn("Bet: $25", output)
        self.assertIn("Balance: $450", output)
        self.assertIn("Bet: $50", output)

    def test_render_board_shows_updated_total_bet_after_double_and_split(self):
        """When hands are doubled or split, total bet shows the sum across all hands."""
        payload = self._make_state_payload()
        # Simulate gambler_1 doubling (hand bet becomes 50)
        payload["players"][0]["hands"][0]["bet"] = 50
        # Simulate gambler_2 splitting into two hands of 50 each (total bet 100)
        payload["players"][1]["hands"] = [
            {"cards": [{"rank": "8", "suit": "D"}, {"rank": "2", "suit": "C"}], "score": 10, "bet": 50, "status": "ACTIVE"},
            {"cards": [{"rank": "8", "suit": "H"}, {"rank": "A", "suit": "S"}], "score": 19, "bet": 50, "status": "ACTIVE"},
        ]
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            client.render_board(payload, "gambler_1")
            output = mock_out.getvalue()
        self.assertIn("Bet: $50", output)
        self.assertIn("Bet: $100", output)

    def test_render_board_shows_player_name(self):
        """When player names are provided, they should be rendered instead of gambler_X."""
        payload = self._make_state_payload()
        payload["players"][0]["name"] = "Alice"
        payload["players"][1]["name"] = "Bob"
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            client.render_board(payload, "gambler_1")
            output = mock_out.getvalue()
        self.assertIn("Alice (You)", output)
        self.assertIn("Bob", output)

    def test_render_board_shows_all_players_cards(self):
        """All players' cards should be visible face-up to everyone at the table."""
        payload = self._make_state_payload()
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            # Viewing as gambler_1; both gambler_1's and gambler_2's cards should be visible
            client.render_board(payload, "gambler_1")
            output = mock_out.getvalue()
        # gambler_1's cards: A♠  5♣
        self.assertIn("A♠", output)
        self.assertIn("5♣", output)
        # gambler_2's cards: 8♦  7♥
        self.assertIn("8♦", output)
        self.assertIn("7♥", output)


class TestClientRenderGameOver(unittest.TestCase):
    """Smoke tests for client.render_game_over()."""

    def _make_game_over_payload(self):
        return {
            "dealer_hand": {
                "cards":  [{"rank": "10", "suit": "HEARTS"},
                            {"rank": "6",  "suit": "DIAMONDS"},
                            {"rank": "6",  "suit": "CLUBS"}],
                "score":  22,
                "status": "BUSTED",
            },
            "results": [
                {
                    "player_id":     "gambler_1",
                    "hand_index":    0,
                    "player_score":  21,
                    "outcome":       "WIN",
                    "payout":        50,
                    "final_balance": 525,
                },
                {
                    "player_id":     "gambler_2",
                    "hand_index":    0,
                    "player_score":  15,
                    "outcome":       "LOSS",
                    "payout":        0,
                    "final_balance": 450,
                },
            ],
        }

    def test_render_game_over_does_not_crash(self):
        payload = self._make_game_over_payload()
        with patch("sys.stdout", new_callable=io.StringIO):
            try:
                client.render_game_over(payload, "gambler_1")
            except Exception as exc:
                self.fail(f"render_game_over raised {exc}")

    def test_render_game_over_shows_win(self):
        payload = self._make_game_over_payload()
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            client.render_game_over(payload, "gambler_1")
            output = mock_out.getvalue()
        self.assertIn("WIN", output)

    def test_render_game_over_shows_loss(self):
        payload = self._make_game_over_payload()
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            client.render_game_over(payload, "gambler_2")
            output = mock_out.getvalue()
        self.assertIn("LOSS", output)

    def test_render_game_over_shows_dealer_bust(self):
        payload = self._make_game_over_payload()
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            client.render_game_over(payload, "gambler_1")
            output = mock_out.getvalue()
        self.assertIn("BUSTED", output)


class TestClientRenderLobby(unittest.TestCase):
    """Smoke tests for client.render_lobby()."""

    def test_render_lobby_does_not_crash(self):
        payload = {
            "message":          "Waiting for Player 2...",
            "current_players":  1,
            "required_players": 2,
            "assigned_id":      "gambler_1",
        }
        with patch("sys.stdout", new_callable=io.StringIO):
            try:
                client.render_lobby(payload, "gambler_1")
            except Exception as exc:
                self.fail(f"render_lobby raised {exc}")

    def test_render_lobby_shows_seat(self):
        payload = {
            "message":          "Waiting...",
            "current_players":  1,
            "required_players": 2,
            "assigned_id":      "gambler_1",
        }
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            client.render_lobby(payload, "gambler_1")
            output = mock_out.getvalue()
        self.assertIn("gambler_1", output)


class TestClientRenderError(unittest.TestCase):
    """Unit tests for client.render_error()."""

    def test_render_error_prints_to_stderr(self):
        payload = {"error_code": "INVALID_MOVE", "message": "Cannot double here."}
        with patch("sys.stderr", new_callable=io.StringIO) as mock_err:
            client.render_error(payload)
            output = mock_err.getvalue()
        self.assertIn("INVALID_MOVE", output)
        self.assertIn("Cannot double here", output)

    def test_render_error_handles_missing_fields(self):
        """render_error should not crash when payload is missing keys."""
        with patch("sys.stderr", new_callable=io.StringIO):
            try:
                client.render_error({})
            except Exception as exc:
                self.fail(f"render_error raised {exc} on empty payload")


class TestClientHandleLobbyWait(unittest.TestCase):
    """Unit tests for client.handle_lobby_wait()."""

    def test_assigned_id_stored_in_state(self):
        state = client.ClientState()
        msg = {
            "msg_type": "LOBBY_WAIT",
            "player_id": "dealer",
            "timestamp": 1,
            "payload": {
                "message":          "Waiting...",
                "current_players":  1,
                "required_players": 2,
                "assigned_id":      "gambler_2",
            },
        }
        with patch("sys.stdout", new_callable=io.StringIO):
            client.handle_lobby_wait(msg, state, MagicMock())
        self.assertEqual(state.player_id, "gambler_2")

    def test_phase_set_to_lobby_wait(self):
        state = client.ClientState()
        msg = {
            "msg_type": "LOBBY_WAIT", "player_id": "dealer", "timestamp": 1,
            "payload": {"assigned_id": "gambler_1", "current_players": 1,
                        "required_players": 2, "message": "hi"},
        }
        with patch("sys.stdout", new_callable=io.StringIO):
            client.handle_lobby_wait(msg, state, MagicMock())
        self.assertEqual(state.phase, client.ClientState.LOBBY_WAIT)


class TestClientHandleStateUpdate(unittest.TestCase):
    """Unit tests for client.handle_state_update()."""

    def _make_msg(self, current_turn):
        return {
            "msg_type": "STATE_UPDATE",
            "player_id": "dealer",
            "timestamp": 1,
            "payload": {
                "last_action":  None,
                "dealer":       {"up_card": {"rank": "10", "suit": "HEARTS"}, "score": 10, "cards": []},
                "players": [
                    {"player_id": "gambler_1", "balance": 475,
                     "hands": [{"cards": [{"rank": "A", "suit": "S"}, {"rank": "5", "suit": "C"}],
                                "score": 16, "bet": 25, "status": "ACTIVE"}]},
                    {"player_id": "gambler_2", "balance": 450,
                     "hands": [{"cards": [{"rank": "8", "suit": "D"}, {"rank": "7", "suit": "H"}],
                                "score": 15, "bet": 50, "status": "ACTIVE"}]},
                ],
                "current_turn": current_turn,
            },
        }

    def test_my_turn_sets_phase(self):
        state           = client.ClientState()
        state.player_id = "gambler_1"
        with patch("sys.stdout", new_callable=io.StringIO):
            client.handle_state_update(self._make_msg("gambler_1"), state, MagicMock())
        self.assertEqual(state.phase, client.ClientState.MY_TURN)

    def test_other_turn_sets_waiting(self):
        state           = client.ClientState()
        state.player_id = "gambler_1"
        with patch("sys.stdout", new_callable=io.StringIO):
            client.handle_state_update(self._make_msg("gambler_2"), state, MagicMock())
        self.assertEqual(state.phase, client.ClientState.WAITING)

    def test_no_current_turn_sets_dealer_phase(self):
        state           = client.ClientState()
        state.player_id = "gambler_1"
        with patch("sys.stdout", new_callable=io.StringIO):
            client.handle_state_update(self._make_msg(None), state, MagicMock())
        self.assertEqual(state.phase, client.ClientState.DEALER_TURN)


class TestClientHandleError(unittest.TestCase):
    """Unit tests for client.handle_error()."""

    def test_handle_error_does_not_modify_state(self):
        state = client.ClientState()
        state.player_id = "gambler_1"
        state.phase     = client.ClientState.MY_TURN
        msg = {
            "msg_type": "ERROR", "player_id": "dealer", "timestamp": 1,
            "payload": {"error_code": "INVALID_MOVE", "message": "No."},
        }
        with patch("sys.stderr", new_callable=io.StringIO):
            client.handle_error(msg, state)
        # Phase should remain unchanged
        self.assertEqual(state.phase, client.ClientState.MY_TURN)

    def test_handle_error_prints_to_stderr(self):
        state = client.ClientState()
        msg = {
            "msg_type": "ERROR", "player_id": "dealer", "timestamp": 1,
            "payload": {"error_code": "NOT_YOUR_TURN", "message": "Wait."},
        }
        with patch("sys.stderr", new_callable=io.StringIO) as mock_err:
            client.handle_error(msg, state)
            output = mock_err.getvalue()
        self.assertIn("NOT_YOUR_TURN", output)


# ===========================================================================
# Run all tests
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
