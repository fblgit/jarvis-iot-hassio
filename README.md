# Jarvis (my version): work n progress

Notes: the code could be better, but I don't have enough time to make it pretty.. but make it works.
       "Talk is free.. commits are not" so feel free to submit some PR.

This project is not for someone with no programming knowledge, I will solve "issues" that affects everyone and study suggestions of features that makes sense and I can apply in my own scenarios...

I will explain how this all ties together..

# ws
Jarvis, control most of the things (Gate, Doorbell, Cast, PIR, Alarm, Text2Speech, IOT Configs, etc) just take a walk thru the code and the endpoints and u'll understand. When i have some spare time i will document it.

# ws-tuya
Tuya webservice needs that you setup your devices on the tuya_devices.py and does a few things:

* RGB Bulbs: this tuya bulbs, cheapy 6U$D, are not really HomeAssistant friendly.. its quite messy. So with this you can set and talk with those bulbs in a simpler way. It's more like a helper that i tied to hassio thru the service and works good with Node-Red for the automations and so.
* Curtains: Home Assistant wasn't able to get the position of the curtain neither able to set to X %.. so i built this one and tied it there to replace the cover position feature of hassio. Works great with sliders and so. It has been tested with TWO different kind of curtains, both works.
* Sensors: I have those ones named Neo, which are Siren+Temp+Humid .. some sort of mix of Zigbee+Gateway2Wireless-to-Tuya. These ones doesn't show up on HomeAssistant, so i coded this piece. for 15 U$D they work quite good and with these endpoints it fulfils my needs. I have around another sensor, that one speaks totally different protocol.. its a "battery" style sensor, I'll work on it when I have some time.

Note: on K8s/Docker this one needs host net privileges.

# phoneguardian
Its a mechanism to keep a track of some IP in your network (mostly your cellphone..) when it goes away u get a OTP to open the gate, when u get back and u are near u get also a new token (I use it to close it..) this is quite safe even to be exposed on internet. The mechanism of the OTP generated by Jarvis and verified by the gate is quite solid. you need pushbullet and ifttt for this (this part of ifttt could be overrided if u code a piece to hit the PB api, but i was doing some other experiments with this things).


# cast_server
This one takes care of the the broadcast itself, in my case. All google home spread around the house. I made this part of the "groups" and "scenes" that u can adjust the time of each scene and tie it to the cast event. So lets say, the doorbell will buzz full power at any time, but the notifications of the washing machine will just sound in the kitchen at a reasonable volume.
I think the part where Jarvis-WS does the TTS and so.. should be moved here, but i will spend the time on something more funnier.
Note: on K8s/Docker this one needs host net privileges.

# sync_serve
Oh.. well, when u have 3,4,5+.. of those google homes, the broadcast is not in sync (by 1-2-3 seconds) so its horrible. I coded this thing that in together with the cast_server is able to put some order (sync) to the cast by flushing the request at the same time when all the speakers are requesting the audio. Look at it as a way to serve 1 file to X devices exactly (almost) at the same time.

# proxy
Simple, an interceptor for debugging without break Jarvis.. i coded it quickly the day that moved the containers of Jarvis into a K8s. But hey, is there for free.

# smartgate
Is how i control the doorbell and the parking door. 
* It requires Jarvis for grabbing his own provisioning config
* It requires Jarvis for the Broadcast
* It requires Jarvis to verify the OneTimePasswords of PhoneGuardian (when they are consumed)
* It runs on a ESP8266 or ESP32 (like mine) 
* It needs a 5v Relay to control the open/close button of the door/gate/etc on any DIGITAL pin
* The doorbell goes into GND + DIGITAL pin
I use platformio for this project on VSCode, could had coded it on MicroPython or similar.. but that wasn't funny enough heh..

# other files
* database schema > i will push soon some sample data for you to understand whats inside there.
* Dockerfile + requirements.txt + start.sh > are the files required to push all this thing. Look at the start.sh so u can understand how i made it. I run it on K8s, and its quite fast for me to push new code in this way.

# things to do
tons of them, linting, pretty.. aint my priority.
So far, i'm working on tensorflow objects and bluetooth low energy (room assistant) kind of thing to control lighting across the house and solve some daily scenarios (I aim to comfort :D)

but hey as I said before, just feel free to contribute with code and stuff.. who knows where this can end.

