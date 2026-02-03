Spreeder
- Read the clipboard's text 
- Open new, small window
- Rapid serial visual presentation of the text (artificial fixation points of each word highlighted)
- Dark background, Dark gray and blue title bar, white text with orange highlights for the fixation points
- Offer wpm adjustment, default to 400wpm, but remember the user's last wpm adjustment between sessions
- Map to F3 when running
- Pressing F3 again will disengage the app, removing the window from the screen
- Press spacebar to "play" clipboard text and begin serial visual presentation
- When app is opened with F3, call OpenAI API to summarize the clipboard's text into short bullet points, in incomplete sentences 
- Return this summary after serial visual presentation is over, or--
"- If the user presses f3 to open the window, but presses SHIFT space instead of just space, display the summary immediately, keep window open until user presses enter or space, then app re-minimizes out of sight"
- If user presses f3 with the app already open, re-minimize out of sight.
- Refer to .env for OpenAI API key
- Write app in python, build UI with CustomTkinter, make font of serial visualization presentation comic sans
