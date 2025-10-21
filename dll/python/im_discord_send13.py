#import imax
import requests
from discord import SyncWebhook
import discord
import os.path

def discord_send(url="", name="", text="", photo_path=""):

#	imax.print('url: ', url)
#	imax.print('text: ', text)
#	imax.print('photo_path: ', photo_path)
	webhook = SyncWebhook.from_url(url)
#	webhook.send(content="Hello World")

#	if (photo_path == "") or (not os.path.isfile(photo_path)):
	if photo_path == "":
		webhook.send(content=text, username=name)
	else:
		if os.path.isfile(photo_path):
			webhook.send(content=text, username=name, file=discord.File(photo_path))
		else:
			imax.print('file does not exist: ', photo_path)
			webhook.send(content=text, username=name)

#discord_send(webhook_url, "abc", "test")
