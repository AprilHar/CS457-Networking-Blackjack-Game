# CS457-Networking-BlackJack-Game
Term Project for CS457 Computer Networks and the Internet. The goal is to create custom application protocols and a game that saves states and has full network connectivity between clients and server.

# Player Turn Mechanics
Player roles are decided by the following:
  - The Server will occupy the role of the dealer
  - Each Client will occupy the role of the player

The Dealer (Server Side):
- Set-Up
  - The server will create a game and wait for players to join.
  - After players have joined and all players have placed their bets the game will start and the dealer will draw 2 cards per player from a couple of shuffled decks. These cards are distributed     face-up to each of the players that have placed a bet. Afterward the dealer will draw one card know as the "Up" card which is placed face-up and one card known as the "Hole" card which is       placed face-down.
  - If the "Up" card is a ten-valued card like a 10, Jack, Queen, or King, the dealer will peek at the "Hole" card to check if a natural blackjack has occurred.
  - If the "Up" card is an Ace the dealer will offer insurance and after it's been accepted or declined by each player the dealer will peek at the "Hole" card to check if a natural blackjack        has occurred and pay out accordingly to insurance.
  
- During Play
  - After the set-up the dealer will go around to each player that has made a bet and if requirements are met will ask if they would like to "Hit", "Stand", "Double Down", or "Split".
    
    - Hit
      - If the player asks to "Hit" the dealer will draw a new card from the shuffled decks, deal it to the player face-up, and move to the next player. A player can always have the option of           hitting unless the player has previously chose "Double Down"
      
    - Stand
      - If the player asks to "Stand" the dealer will do nothing and move to the next player. A player can always have the option of standing unless the player has previously chose "Double Down"
      
    - Double Down
      - If the player has at least an equal amount of money in their account to their initial bet the dealer will give the player a third option to "Double Down" the dealer will "Hit" the               player and then the player will automatically "Stand" for the rest of the current hand. After the dealer moves to the next player.
  
    - Split
      - If a player is dealt a pair of cards at the start of the hand and has at least an equal amount of money in their account to their initial bet, the dealer will give the player a forth            option to "Split" during the first round. If a player chooses to "Split" the dealer will split the pair into two new hands and deal a new card for each hand so the player has two hands          of two cards each. The dealer will also have the player put an equal bet on the newly created hand. After the dealer moves to the next player.
  - After each player has either chose to "Stand" or has lost via the win/lose conditions the dealer will flip the "Hole" card and reveal it to the players.
  - If the dealer's total value of their cards is less than 17 the dealer must "Hit" until the total value of their cards is greater than or equal to 17. After the this condition is met the         dealer will check to see what win/lose condition has been met for each player.

The Player (Client Side):
- Set-Up
  - Each Player will receive a player number based off the order the clients join in when the server is first initialized. If a client loses connection to the server the client will keep the        player number it had before disconnecting unless the server restarts in the meantime.
  - After connecting to the server and joining the game each player will select an amount of money to bet. Placing the bet will tell the server that player is ready to play. The players will        then be dealt cards and given options by the dealer.
  - If the dealer offers insurance each player is allowed to make an additional side bet for up to 50% of their initial bet on whether the dealer has a natural blackjack.
  
- During Play
  - Each round when it's their turn a Player can choose to either "Hit", "Stand", "Double Down", or "Split" if requirements for each option are met.


# Win/Lose/Tie Conditions
Win:
  - If the player has a higher total than the dealer at the end of the round, that player wins.
  - If the dealer's total goes over a total of 21, all players that didn't also go over win.
  - Win without Blackjack is paid out at a 1:1 ratio
  - Win with Blackjack is paid out at a 3:2 ratio

Lose:
  - If the dealer has a higher total than the player at the end of the round, that player loses.
  - If the player goes over a total of 21, that player loses.
  - If player loses bet money is lost to the dealer

Tie:
  - If the dealer and the player has the same total value at the end the game is tied and the bet is returned to the player.

Insurance:
  - If a player has insurance and the dealer has a natural blackjack the bet is paid out at a 2:1 ratio
