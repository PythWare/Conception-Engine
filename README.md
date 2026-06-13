# Conception Engine

Conception Engine is a toolkit being designed for Conception 1/Plus and Conception 2. Included tools are an unpacker for both games that unpacks, decompresses, etc the CFSI containers (all files unpack with proper filenames and reconstructed filepaths), a Mod Creator that turns modded files into Mod Manager compatible mods, and a Mod Manager that has a deluxe GUI that no other Mod Manager is similar to other than Aldnoah Engine's Constellation Mod Manager and Dynasty Warriors 4 Hyper's Aquatic Mod Manager as of 2026.

Scroll to the bottom to see GUI examples of the toolkit if you desire.

This new engine is meant to replace the old modding tools I made for the Conception games in the past now that i'm more experienced with tkinter/python.

If you have issues make sure to read this readme before creating an issue or contacting me on reddit/github.

# Requirements

Python 3, Pillow (installed in admin command prompt with `python -m pip install pillow`) which is a Python imaging library, and windows (Conception Engine isn't supported for linux/mac usage).

Also, DON'T you dare delete the json Conception Engine creates while unpacking the games. That json is a new approach i'm doing for taildata handling. In the past I would append taildata to the end of each unpacked file, now a more efficient method i'm doing is storing metadata/taildata in a single json for the Mod Creator/Mod Manager to rely on for Mod Package Creation and Mod applying/disabling. 

So the quicky? Don't delete the json unless you're running a new unpack because the Mod Creator/Mod Manager rely on that json for proper and safe Mod Creation, Mod Applying, and Mod Disabling. Avoid editing the json unless you know what you're doing.

# How to run

double click main.pyw, should run after that. If it has issues with double clicking then open cmd in the current directory and type `python main.pyw`

If Conception Engine does not launch it's usually caused by Python not being installed correctly or .pyw file associations using the wrong Python. Please verify your Python installation before reporting a bug.

Back up your game files before using Conception Engine.

# Controls for Main Hub

The GUI for the Main Hub is intentionally designed to be unique, it doesn't look like a standard GUI app. 

To move the app around you must use right click on the GUI (the vertical buttons or the title of the app).

To exit out of Conception Engine, click the esc button on your keyboard.

Press F1 to toggle on/off always on top mode.

Editor panels can be moved by dragging their title bars.

# T and G spherical buttons

T is where the modding software live while G is the Guide section for Conception Engine, all you need to do is left click the T or G spheres for whatever you're wanting to use. I suggest reading the Guide section (click the G sphere) before using the tools.

# Royal Archive Mod Manager

A deluxe mod manager, meant to make managing mods a pleasant experience. The idea is a library, a bookshelf with mods visualized as books on the shelves that match the genre a mod belongs to. Selecting a book/mod displays metadata (author, version, etc), preview images, description, and optional audio playback (a toggle is included that disables audio playback for mods within Mod Manager for those who don't want to listen to a mod's music/audio) etc. Titles of Mods are placed on the spine of the books/mods, meant to be book-like. Invalid mods are placed on the quarantine shelf. The Mod Manager will be used to enable/disable package mods.

<img width="1920" height="1036" alt="con7" src="https://github.com/user-attachments/assets/b0c4c8ab-c5d9-439d-8e57-846c68175f97" />

<img width="1920" height="1036" alt="con8" src="https://github.com/user-attachments/assets/2c44e284-8aab-4cca-9767-529df777bb34" />

# Main Hub

The toolkit uses a custom GUI I designed, intentionally meant to not look like most apps.

The unpacker will unpack all the CFSI containers for Conception 1 and 2, decompress the files that have compression, and create a json that stores metadata/taildata for Mod Creator/Mod Manager usage.

<img width="1113" height="733" alt="con1" src="https://github.com/user-attachments/assets/b9671009-fe12-444c-8625-da7b3400b899" />

<img width="1123" height="740" alt="con9" src="https://github.com/user-attachments/assets/5368877e-fa5c-4b84-b0da-cb2b0d59c866" />

# Mod Creator

The Mod Creator is what's used to turn modded files into Mod Manager compatible mod packages. Mod Creator will create custom mod formats I designed that includes metadata (author, version, description of mod), genre type for the mod, preview images for the mod, optional wav file included for theme/music with the mod, etc.

<img width="1143" height="756" alt="con6" src="https://github.com/user-attachments/assets/a0904f77-1806-494f-b405-b642c172fed0" />
