# CS457-Networking-BlackJack-Game
Term Project for CS457 Computer Networks and the Internet. The goal is to create custom application protocols and a game that saves states and has full network connectivity between clients and server.

# Player Turn Mechanics
Player roles are decided by the following:
  - The Server will occupy the role of the dealer
  - Each Client will occupy the role of the player

The Dealer (Server Side):
- Set-Up
  The dealer will draw 2 cards per player from a couple of shuffled decks. These cards are distributed face-up to each of the players that have placed a bet. Afterward the dealer will draw one    card know as the "Up" card which is placed face-up and one card known as the "Hole" card which is placed face-down. If the "Up" card is a ten-valued card like a 10, Jack, Queen, or King, the    dealer will peek at the "Hole" card to check if a natural blackjack has occurred. If the "Up" card is an Ace the dealer will offer insurance and after it's been accepted or declined by each     player the dealer will peek at the "Hole" card to check if a natural blackjack has occurred and pay out accordingly to insurance.
  
- During Play
  After the set-up the dealer will go around to each player that has made a bet and if requirements are met will ask if they would like to "Hit", "Stand", "Double Down", or "Split".
  
  - Hit
    If the player asks to "Hit" the dealer will draw a new card from the shuffled decks, deal it to the player face-up, and move to the next player. A player can always have the option of           hitting unless the player has previously chose "Double Down"
    
  - Stand
    If the player asks to "Stand" the dealer will do nothing and move to the next player. A player can always have the option of standing unless the player has previously chose "Double Down"
    
  - Double Down
    If the player has at least an equal amount of money in their account to their initial bet the dealer will give the player a third option to "Double Down" the dealer will "Hit" the player        and then the player will automatically "Stand" for the rest of the current hand. After the dealer moves to the next player.

  - Split
    If a player is dealt a pair of cards at the start of the hand and has at least an equal amount of money in their account to their initial bet, the dealer will give the player a forth option     to "Split" during the first round. If a player chooses to "Split" the dealer will split the pair into two new hands and deal a new card for each hand so the player has two hands of two          cards each. The dealer will also have the player put an equal bet on the newly created hand. After the dealer moves to the next player.

