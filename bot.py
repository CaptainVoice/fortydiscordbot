# This is the main file for the Discord bot.
import discord
from discord import app_commands, ui
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Bot Setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True  # Required for fetching guild members and roles

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# --- Title and Body Modal ---
class MessageModal(ui.Modal, title='Message Content'):
    msg_title = ui.TextInput(label='Title', style=discord.TextStyle.short, required=True)
    body = ui.TextInput(label='Body', style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        # Store title and body in the view for later access
        # This is a bit of a workaround as modal state isn't directly passed back easily
        # to the initial command callback or a subsequent view.
        # We'll attach it to the interaction object for now, though ideally,
        # this would be managed through a more robust state mechanism or view properties.
        interaction.namespace.msg_title = self.msg_title.value
        interaction.namespace.body = self.body.value
        await interaction.response.defer() # Defer to allow for role selection next

# --- Role Select View ---
class RoleSelectView(ui.View):
    def __init__(self, guild_roles: list[discord.Role], original_interaction: discord.Interaction, selected_channel_id: int):
        super().__init__(timeout=180)
        self.original_interaction = original_interaction
        self.selected_channel_id = selected_channel_id
        self.selected_roles = []

        # Role Select Dropdown
        role_options = [
            discord.SelectOption(label=role.name, value=str(role.id))
            for role in guild_roles if role.name != "@everyone" # Exclude @everyone
        ]
        if not role_options: # Handle case with no roles
             role_options.append(discord.SelectOption(label="No roles available", value="no_roles"))


        self.role_select = ui.Select(
            placeholder="Select roles to mention (optional)",
            options=role_options,
            max_values=len(role_options) if role_options[0].value != "no_roles" else 1, # Allow multiple selections
            row=0
        )
        self.role_select.callback = self.role_select_callback
        self.add_item(self.role_select)

        # Send Message Button
        self.send_button = ui.Button(label="Send Message", style=discord.ButtonStyle.green, row=1)
        self.send_button.callback = self.send_button_callback
        self.add_item(self.send_button)

        # Skip/No Roles Button
        self.skip_button = ui.Button(label="Skip Role Mention", style=discord.ButtonStyle.grey, row=1)
        self.skip_button.callback = self.skip_button_callback
        self.add_item(self.skip_button)


    async def role_select_callback(self, interaction: discord.Interaction):
        if "no_roles" in self.role_select.values:
            self.selected_roles = []
            await interaction.response.send_message("No roles selected or available.", ephemeral=True)
            return

        self.selected_roles = [discord.Object(id=int(role_id)) for role_id in self.role_select.values]
        await interaction.response.send_message(f"Selected roles: {', '.join([r.mention for r in self.selected_roles]) if self.selected_roles else 'None'}", ephemeral=True)


    async def send_button_callback(self, interaction: discord.Interaction):
        await self.send_message_action(interaction, self.selected_roles)

    async def skip_button_callback(self, interaction: discord.Interaction):
        await self.send_message_action(interaction, [])


    async def send_message_action(self, interaction: discord.Interaction, roles_to_mention: list[discord.Object]):
        # Retrieve title and body from the interaction namespace
        msg_title = interaction.namespace.msg_title
        body = interaction.namespace.body
        selected_channel_id = self.selected_channel_id

        channel = client.get_channel(selected_channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Error: Could not find the selected channel.", ephemeral=True)
            return

        embed = discord.Embed(title=msg_title, description=body, color=discord.Color.blue())
        
        role_mentions_str = ""
        if roles_to_mention:
            role_mentions_str = " ".join([f"<@&{role.id}>" for role in roles_to_mention])

        try:
            await channel.send(content=role_mentions_str if role_mentions_str else None, embed=embed)
            await interaction.response.send_message(f"Message sent to {channel.mention}!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Error: I don't have permission to send messages to that channel.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"An unexpected error occurred: {e}", ephemeral=True)
        
        self.stop() # Stop the view after the message is sent or an error occurs

# --- Channel Select View ---
class ChannelSelectView(ui.View):
    def __init__(self, text_channels: list[discord.TextChannel], original_interaction: discord.Interaction):
        super().__init__(timeout=180)
        self.original_interaction = original_interaction
        self.selected_channel_id = None

        options = [
            discord.SelectOption(label=f"#{channel.name}", value=str(channel.id))
            for channel in text_channels
        ]
        if not options: # Handle case with no text channels
            options.append(discord.SelectOption(label="No text channels found", value="no_channels"))

        self.channel_select = ui.Select(
            placeholder="Select a channel",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.channel_select.callback = self.channel_select_callback
        self.add_item(self.channel_select)

    async def channel_select_callback(self, interaction: discord.Interaction):
        if self.channel_select.values[0] == "no_channels":
            await interaction.response.send_message("No text channels available to send a message to.", ephemeral=True)
            self.stop()
            return

        self.selected_channel_id = int(self.channel_select.values[0])
        # Store selected channel ID in the interaction namespace for the modal and role view
        interaction.namespace.selected_channel_id = self.selected_channel_id
        
        # Show the message modal
        message_modal = MessageModal()
        await interaction.response.send_modal(message_modal)
        await message_modal.wait() # Wait for modal submission

        # After modal submission, show role selection view
        # The title and body are now in interaction.namespace
        if hasattr(interaction.namespace, 'msg_title') and hasattr(interaction.namespace, 'body'):
            guild_roles = interaction.guild.roles
            role_view = RoleSelectView(guild_roles, self.original_interaction, self.selected_channel_id)
            # We need to send a new message or edit the original placeholder for the role select view
            # Since the modal interaction was deferred, we can use followup.send
            await self.original_interaction.followup.send("Please select roles to mention (optional):", view=role_view, ephemeral=True)
        else:
            # This case should ideally not happen if modal submission is handled correctly
            await self.original_interaction.followup.send("Failed to get message content from modal.", ephemeral=True)
        
        self.stop() # Stop this view as its job is done

@tree.command(name="sendmessage", description="Sends a custom message to a specified channel.")
async def send_message_command(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    text_channels = [ch for ch in interaction.guild.text_channels if ch.permissions_for(interaction.guild.me).send_messages]
    
    if not text_channels:
        await interaction.response.send_message("I don't have permission to send messages in any channel, or no text channels exist.", ephemeral=True)
        return

    # Using interaction.namespace to pass data between interaction handlers
    interaction.namespace = discord.utils.Namespace()

    view = ChannelSelectView(text_channels, interaction)
    await interaction.response.send_message("Please select a channel to send the message to:", view=view, ephemeral=True)


@client.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("Commands synced.")
    print("------")

if __name__ == "__main__":
    if DISCORD_TOKEN:
        client.run(DISCORD_TOKEN)
    else:
        print("Error: DISCORD_TOKEN not found in .env file.")
