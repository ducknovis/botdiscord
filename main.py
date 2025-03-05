import discord
from discord.ext.commands import Bot
from discord import Intents
from discord.ui import Button, View
import os
import random
import uuid
import asyncio

# Lấy token từ Secrets
TOKEN = os.getenv("DISCORD_TOKEN")

# Thiết lập intents
intents = Intents.default()
intents.message_content = True  # Cho phép bot đọc nội dung tin nhắn
intents.members = True  # Cho phép bot theo dõi thành viên

# Tạo bot
bot = Bot(command_prefix="!", intents=intents)

# Lưu trữ thông tin game (channel_id, participants, message, cards, decisions, game_id, player_messages, start_votes)
games = {}

# Bộ bài 52 lá (13 giá trị x 4 chất)
SUITS = ["rô", "bích", "chuồn", "tép"]
VALUES = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
DECK = [f"{value} {suit}" for suit in SUITS for value in VALUES]

class StartButton(Button):
    def __init__(self):
        super().__init__(label="Bắt đầu", style=discord.ButtonStyle.success)

    async def callback(self, interaction):
        channel_id = interaction.channel_id
        if channel_id not in games:
            await interaction.response.send_message("Không có trò chơi nào đang diễn ra!", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id not in games[channel_id]["participants"]:
            await interaction.response.send_message("Bạn không tham gia trò chơi này!", ephemeral=True)
            return

        if "start_votes" not in games[channel_id]:
            games[channel_id]["start_votes"] = set()
        games[channel_id]["start_votes"].add(user_id)

        participant_count = len(games[channel_id]["participants"])
        votes_count = len(games[channel_id]["start_votes"])

        if votes_count == participant_count:
            await interaction.response.defer()  # Báo cho Discord rằng bot đang xử lý
            message = games[channel_id]["message"]
            await start_gameplay(interaction, channel_id, message)
            followup_msg = await interaction.followup.send("Trò chơi đã bắt đầu! Nhấn nút 'Bốc bài' để nhận lá bài của bạn.", ephemeral=True)
            await asyncio.sleep(2)  # Đợi 2 giây
            await followup_msg.delete()  # Xóa tin nhắn ephemeral sau 2 giây
        else:
            await interaction.response.send_message(
                f"Bạn đã nhấn 'Bắt đầu'. Cần {participant_count} người tham gia nhấn nút để bắt đầu trò chơi. Hiện có {votes_count}/{participant_count} người.",
                ephemeral=True
            )

class JoinButton(Button):
    def __init__(self):
        super().__init__(label="Tham gia", style=discord.ButtonStyle.primary)

    async def callback(self, interaction):
        channel_id = interaction.channel_id
        if channel_id not in games:
            await interaction.response.send_message("Không có trò chơi nào đang diễn ra!", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id in games[channel_id]["participants"]:
            await interaction.response.send_message("Bạn đã tham gia rồi!", ephemeral=True)
            return

        if len(games[channel_id]["participants"]) >= 5:
            await interaction.response.send_message("Trò chơi đã đầy (tối đa 5 người)!", ephemeral=True)
            return

        games[channel_id]["participants"].add(user_id)

        participant_count = len(games[channel_id]["participants"])
        message = games[channel_id]["message"]
        await message.edit(content=f"Tham gia chơi xì dách\nHiện có {participant_count} người tham gia\nNhấn 'Bắt đầu' để chơi.")
        await interaction.response.send_message(
            f"Bạn đã tham gia trò chơi! Hiện có {participant_count} người tham gia.", ephemeral=True
        )

        # Nếu đủ 1 người, thêm nút "Bắt đầu" vào view hiện tại (không cần 2 người nữa vì bot là nhà cái)
        if participant_count >= 1:
            view = discord.ui.View(timeout=None)
            view.add_item(JoinButton())  # Giữ nút "Tham gia"
            view.add_item(StartButton())  # Thêm nút "Bắt đầu"
            await message.edit(view=view)  # Chỉnh sửa view của tin nhắn gốc

class DrawButton(Button):
    def __init__(self, user_id, game_id):
        super().__init__(label="Bốc bài", style=discord.ButtonStyle.primary, custom_id=f"draw_{user_id}_{game_id}")
        self.user_id = user_id
        self.game_id = game_id  # Thêm game_id để nhận diện trận đấu

    async def callback(self, interaction):
        channel_id = interaction.channel_id
        if channel_id not in games or "game_id" not in games[channel_id]:
            await interaction.response.send_message("Không tìm thấy thông tin trận đấu. Vui lòng kiểm tra lại!", ephemeral=True)
            return

        # Kiểm tra game_id để đảm bảo tương tác đúng với trận đấu
        if games[channel_id]["game_id"] != self.game_id:
            await interaction.response.send_message("ID trận đấu không hợp lệ. Vui lòng kiểm tra lại!", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id != self.user_id:
            await interaction.response.send_message("Bốc nhầm r", ephemeral=True)
            return

        if user_id not in games[channel_id]["participants"]:
            await interaction.response.send_message("Bạn không tham gia trò chơi này!", ephemeral=True)
            return

        # Bốc 2 lá ngay khi nhấn "Bốc bài"
        if "cards" not in games[channel_id] or user_id not in games[channel_id].get("cards", {}):
            games[channel_id]["cards"][user_id] = []
            for _ in range(2):  # Bốc 2 lá ngay lập tức
                card = random.choice(DECK)
                DECK.remove(card)
                games[channel_id]["cards"][user_id].append(card)

            # Kiểm tra Xì dách hoặc Xì Bàng ngay sau khi bốc 2 lá
            if check_special_hands(games[channel_id]["cards"][user_id], 2):
                cards_str = "\n".join([f"{i+1}. {card}" for i, card in enumerate(games[channel_id]["cards"][user_id])])
                total = calculate_score(games[channel_id]["cards"][user_id])
                special_hand = "Xì Bàng" if check_xi_bang(games[channel_id]["cards"][user_id]) else "Xì dách"
                await interaction.response.send_message(
                    f"Lá của bạn:\n{cards_str}\nTổng điểm: {total}\nBạn đã thắng ngay với {special_hand}!",
                    ephemeral=True
                )
                games[channel_id]["decisions"][user_id] = "Ngừng"
                if all(decision == "Ngừng" for decision in games[channel_id]["decisions"].values() if decision is not None):
                    await end_game(channel_id, games[channel_id]["game_id"])
                return

        user = interaction.user
        cards = games[channel_id]["cards"][user_id]
        cards_str = "\n".join([f"{i+1}. {card}" for i, card in enumerate(cards)])
        total = calculate_score(cards)

        view = View(timeout=None)
        view.add_item(CardButton("Bốc tiếp", user_id, self.game_id))  # Truyền game_id
        view.add_item(CardButton("Ngừng", user_id, self.game_id))  # Truyền game_id

        try:
            # Gửi tin nhắn ephemeral trong channel để ẩn bài (chỉ người chơi thấy)
            msg = await interaction.response.send_message(
                f"Lá của bạn:\n{cards_str}\nTổng điểm: {total}", view=view, ephemeral=True
            )
            # Lưu ID tin nhắn ephemeral để quản lý sau này
            if channel_id not in games or "player_messages" not in games[channel_id]:
                if channel_id not in games:
                    games[channel_id] = {}
                games[channel_id]["player_messages"] = {}
            games[channel_id]["player_messages"][user_id] = msg.id
        except Exception as e:
            print(f"Lỗi khi gửi tin nhắn ephemeral cho {user.name}: {e}")
            await interaction.followup.send(
                f"Lá của bạn:\n{cards_str}\nTổng điểm: {total}", view=view, ephemeral=True
            )
            message = await interaction.original_response()
            games[channel_id]["player_messages"][user_id] = message.id

class CardButton(Button):
    def __init__(self, action, user_id, game_id):
        super().__init__(label=action, style=discord.ButtonStyle.primary, custom_id=f"card_{action}_{user_id}_{game_id}")
        self.action = action
        self.user_id = user_id
        self.game_id = game_id  # Thêm game_id để nhận diện trận đấu

    async def callback(self, interaction):
        channel_id = interaction.channel_id
        # Chỉ kiểm tra game_id, không báo lỗi "Không có trò chơi nào đang diễn ra!" nếu game_id hợp lệ
        if channel_id not in games or "game_id" not in games[channel_id]:
            await interaction.response.send_message("Không tìm thấy thông tin trận đấu. Vui lòng kiểm tra lại!", ephemeral=True)
            return

        # Kiểm tra game_id để đảm bảo tương tác đúng với trận đấu
        if games[channel_id]["game_id"] != self.game_id:
            await interaction.response.send_message("ID trận đấu không hợp lệ. Vui lòng kiểm tra lại!", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id != self.user_id:
            await interaction.response.send_message("Bốc nhầm r", ephemeral=True)
            return

        if user_id not in games[channel_id]["participants"]:
            await interaction.response.send_message("Bạn không tham gia trò chơi này!", ephemeral=True)
            return

        # Kiểm tra xem 'cards' đã được khởi tạo chưa, nếu không thì bỏ qua thay vì báo lỗi
        if "cards" not in games[channel_id] or user_id not in games[channel_id].get("cards", {}):
            await interaction.response.send_message("Dữ liệu lá bài của bạn không sẵn sàng. Vui lòng bấm 'Bốc bài' để bắt đầu!", ephemeral=True)
            return

        user = interaction.user
        if self.action == "Bốc tiếp":
            if len(games[channel_id]["cards"][user_id]) >= 5:
                # Kiểm tra Ngũ Linh khi có 5 lá
                total = calculate_score(games[channel_id]["cards"][user_id])
                if len(games[channel_id]["cards"][user_id]) == 5 and total <= 21:
                    cards_str = "\n".join([f"{i+1}. {card}" for i, card in enumerate(games[channel_id]["cards"][user_id])])
                    await interaction.response.send_message(
                        f"Lá của bạn:\n{cards_str}\nTổng điểm: {total}\nBạn đã thắng ngay với Ngũ Linh!",
                        ephemeral=True
                    )
                    games[channel_id]["decisions"][user_id] = "Ngừng"
                    if all(decision == "Ngừng" for decision in games[channel_id]["decisions"].values() if decision is not None):
                        await end_game(channel_id, games[channel_id]["game_id"])
                    return

            await interaction.response.defer()  # Tránh timeout
            card = random.choice(DECK)
            DECK.remove(card)
            games[channel_id]["cards"][user_id].append(card)

            cards = games[channel_id]["cards"][user_id]  # Lấy toàn bộ lá bài để tính tổng điểm
            total = calculate_score(cards)
            cards_str = "\n".join([f"{i+1}. {card}" for i, card in enumerate(cards)])  # Hiển thị toàn bộ lá bài

            view = View(timeout=None)
            view.add_item(CardButton("Bốc tiếp", user_id, self.game_id))  # Truyền game_id
            view.add_item(CardButton("Ngừng", user_id, self.game_id))  # Truyền game_id

            try:
                # Tạo tin nhắn ephemeral mới thay vì chỉnh sửa tin nhắn cũ
                msg = await interaction.followup.send(
                    f"Lá của bạn:\n{cards_str}\nTổng điểm: {total}", view=view, ephemeral=True
                )
                # Lưu ID tin nhắn ephemeral mới để quản lý
                if channel_id not in games or "player_messages" not in games[channel_id]:
                    if channel_id not in games:
                        games[channel_id] = {}
                    games[channel_id]["player_messages"] = {}
                games[channel_id]["player_messages"][user_id] = msg.id
            except Exception as e:
                print(f"Lỗi khi gửi tin nhắn ephemeral mới cho {user.name}: {e}")
                await interaction.followup.send(
                    f"Lá của bạn:\n{cards_str}\nTổng điểm: {total}", view=view, ephemeral=True
                )
                message = await interaction.original_response()
                games[channel_id]["player_messages"][user_id] = message.id
        else:  # Ngừng
            await interaction.response.defer()
            games[channel_id]["decisions"][user_id] = "Ngừng"
            cards_str = "\n".join([f"{i+1}. {card}" for i, card in enumerate(games[channel_id]["cards"][user_id])])
            total = calculate_score(games[channel_id]["cards"][user_id])

            try:
                # Chỉnh sửa tin nhắn ephemeral hiện tại của người chơi trong channel, xóa view
                if channel_id in games and user_id in games[channel_id]["player_messages"]:
                    message_id = games[channel_id]["player_messages"][user_id]
                    message = await interaction.channel.fetch_message(message_id)
                    await message.edit(
                        content=f"Lá của bạn:\n{cards_str}\nTổng điểm: {total}",
                        view=None
                    )
                else:
                    # Nếu không tìm thấy tin nhắn, gửi tin nhắn ephemeral mới (dự phòng)
                    await interaction.response.send_message(
                        f"Lá của bạn:\n{cards_str}\nTổng điểm: {total}", ephemeral=True
                    )
            except Exception as e:
                print(f"Lỗi khi chỉnh sửa tin nhắn ephemeral cho {user.name}: {e}")
                await interaction.followup.send(
                    f"Lá của bạn:\n{cards_str}\nTổng điểm: {total}", ephemeral=True
                )

            # Loại bỏ tự động xóa tin nhắn ephemeral sau 2 giây cho hành động "Ngừng"
            await interaction.followup.send("Bạn đã chọn ngừng. Kiểm tra tin nhắn riêng trong channel để xem lá bài của bạn. Vui lòng chờ kết quả!", ephemeral=True)

            # Kiểm tra nếu tất cả người chơi đã chọn "Ngừng" và đủ tuổi
            all_stopped = all(decision == "Ngừng" for decision in games[channel_id]["decisions"].values() if decision is not None)
            if all_stopped:
                # Xử lý lượt của nhà cái (bot)
                dealer_cards = games[channel_id]["cards"].get("bot_dealer", [])
                if not dealer_cards:  # Nếu nhà cái chưa có bài, chia 2 lá
                    for _ in range(2):
                        card = random.choice(DECK)
                        DECK.remove(card)
                        dealer_cards.append(card)
                    games[channel_id]["cards"]["bot_dealer"] = dealer_cards

                dealer_total = calculate_score(dealer_cards)
                while dealer_total < 15 and len(dealer_cards) < 5:  # Nhà cái rút thêm nếu < 15 điểm, tối đa 5 lá
                    card = random.choice(DECK)
                    DECK.remove(card)
                    dealer_cards.append(card)
                    dealer_total = calculate_score(dealer_cards)

                # Kiểm tra Xì dách, Xì Bàng, Ngũ Linh cho nhà cái
                if check_special_hands(dealer_cards, 2) and len(dealer_cards) == 2:
                    reveal_text = "Nhà cái (Bot) đã thắng ngay với Xì Bàng!" if check_xi_bang(dealer_cards) else "Nhà cái (Bot) đã thắng ngay với Xì dách!"
                    await games[channel_id]["message"].channel.send(reveal_text)
                elif len(dealer_cards) == 5 and dealer_total <= 21:
                    reveal_text = f"Nhà cái (Bot) đã thắng ngay với Ngũ Linh (Tổng: {dealer_total})!"
                    await games[channel_id]["message"].channel.send(reveal_text)
                else:
                    games[channel_id]["cards"]["bot_dealer"] = dealer_cards

                # Kiểm tra điểm của từng người chơi và nhà cái, chỉ những người đủ tuổi (≥ 16 cho người chơi, ≥ 15 cho nhà cái) mới được tính
                valid_players = []
                scores = {}
                for user_id in participants:
                    total = calculate_score(games[channel_id]["cards"].get(user_id, []))
                    if total >= 16:  # Người chơi cần ≥ 16
                        valid_players.append(user_id)
                        scores[user_id] = total
                dealer_total = calculate_score(games[channel_id]["cards"].get("bot_dealer", []))
                if dealer_total >= 15:  # Nhà cái cần ≥ 15
                    valid_players.append("bot_dealer")
                    scores["bot_dealer"] = dealer_total

                if not valid_players:
                    await games[channel_id]["message"].channel.send("Không có người chơi hoặc nhà cái nào đủ tuổi (≥ 16 cho người chơi, ≥ 15 cho nhà cái)! Trò chơi kết thúc mà không có người thắng.")
                else:
                    reveal_text = f"Kết quả trò chơi (ID trận đấu: {game_id}):\n"
                    max_score = -1
                    winner = None
                    for user_id in valid_players:
                        if user_id == "bot_dealer":
                            user_mention = "Nhà cái (Bot)"
                            cards_str = ", ".join(games[channel_id]["cards"].get("bot_dealer", []))
                        else:
                            user_mention = bot.get_user(user_id).mention
                            cards_str = ", ".join(games[channel_id]["cards"].get(user_id, []))
                        score = scores[user_id]
                        reveal_text += f"{user_mention}: {cards_str} (Tổng: {score})\n"
                        if score <= 21 and score > max_score:
                            max_score = score
                            winner = user_id

                    if winner:
                        reveal_text += f"\nNgười thắng: {'Nhà cái (Bot)' if winner == 'bot_dealer' else bot.get_user(winner).mention} với tổng {max_score}!"
                    else:
                        reveal_text += "\nKhông có người thắng (tất cả vượt quá 21 điểm hoặc không đủ tuổi)!"

                    await games[channel_id]["message"].channel.send(reveal_text)

async def start_gameplay(interaction, channel_id, message):
    global DECK
    DECK = [f"{value} {suit}" for suit in SUITS for value in VALUES]
    random.shuffle(DECK)

    # Tạo ID duy nhất cho trận đấu
    game_id = str(uuid.uuid4())

    participants = games[channel_id]["participants"]
    games[channel_id]["cards"] = {user_id: [] for user_id in participants}
    games[channel_id]["cards"]["bot_dealer"] = []  # Thêm nhà cái bot
    games[channel_id]["decisions"] = {user_id: None for user_id in participants}
    games[channel_id]["decisions"]["bot_dealer"] = None  # Thêm quyết định cho nhà cái bot
    games[channel_id]["game_id"] = game_id  # Lưu game_id
    if "player_messages" not in games[channel_id]:
        games[channel_id]["player_messages"] = {}

    # Xử lý nhà cái (bot) trước
    dealer_cards = []
    for _ in range(2):  # Chia 2 lá cho nhà cái (bot)
        card = random.choice(DECK)
        DECK.remove(card)
        dealer_cards.append(card)
    games[channel_id]["cards"]["bot_dealer"] = dealer_cards

    # Kiểm tra Xì dách hoặc Xì Bàng cho nhà cái (bot)
    if check_special_hands(dealer_cards, 2):
        await interaction.channel.send(
            "Nhà cái (Bot) đã thắng ngay với Xì Bàng!" if check_xi_bang(dealer_cards) else "Nhà cái (Bot) đã thắng ngay với Xì dách!"
        )
        games[channel_id]["decisions"]["bot_dealer"] = "Ngừng"
        if all(decision == "Ngừng" for decision in games[channel_id]["decisions"].values() if decision is not None):
            await end_game(channel_id, games[channel_id]["game_id"])
        return

    # Tạo view với nút "Bốc bài" cho người chơi (không cho nhà cái bot)
    for user_id in participants:
        user = bot.get_user(user_id)
        view = View(timeout=None)
        view.add_item(DrawButton(user_id, game_id))  # Thêm nút "Bốc bài" cho người chơi
        try:
            await interaction.channel.send(
                f"{user.mention}, hãy nhấn nút 'Bốc bài' để bắt đầu trò chơi.", view=view
            )
        except Exception as e:
            print(f"Lỗi khi gửi tin nhắn công khai cho {user.name}: {e}")
            followup_msg = await interaction.followup.send(
                f"{user.mention}, hãy nhấn nút 'Bốc bài' để bắt đầu trò chơi.", view=view, ephemeral=True
            )
            await asyncio.sleep(2)  # Đợi 2 giây
            await followup_msg.delete()  # Xóa tin nhắn ephemeral sau 2 giây

    # Hiển thị bài của nhà cái (bot) (ẩn 1 lá nếu cần, nhưng hiện tại hiển thị cả 2 lá để đơn giản)
    dealer_cards = games[channel_id]["cards"]["bot_dealer"]
    await interaction.channel.send(
        f"Nhà cái (Bot): {', '.join(dealer_cards)} (Tổng: {calculate_score(dealer_cards)})"
    )

async def end_game(channel_id, game_id):
    if channel_id not in games or games[channel_id]["game_id"] != game_id:
        return  # Không làm gì nếu không tìm thấy trận đấu hợp lệ

    # Xử lý đã được thực hiện trong callback của "Ngừng"

def calculate_score(cards):
    score = 0
    aces = 0
    for card in cards:
        value = card.split()[0]
        if value == "A":
            aces += 1
        elif value in ["K", "Q", "J"]:
            score += 10
        else:
            score += int(value)

    # Tính điểm cho các lá A, ưu tiên giá trị 11, 10, hoặc 1 sao cho có lợi nhất (≤ 21)
    for _ in range(aces):
        if score + 11 <= 21:
            score += 11
        elif score + 10 <= 21:
            score += 10
        else:
            score += 1

    return score

def check_special_hands(cards, card_count):
    if card_count != 2:
        return False
    if len(cards) != 2:
        return False
    value1, value2 = cards[0].split()[0], cards[1].split()[0]
    if value1 == "A" and value2 in ["10", "J", "Q", "K"]:
        return True
    if value2 == "A" and value1 in ["10", "J", "Q", "K"]:
        return True
    return False

def check_xi_bang(cards):
    if len(cards) != 2:
        return False
    value1, value2 = cards[0].split()[0], cards[1].split()[0]
    return value1 == "A" and value2 == "A"

@bot.tree.command(name="xidach", description="Bắt đầu trò chơi xì dách")
async def xidach_slash(interaction: discord.Interaction):
    await start_game(interaction)

@bot.command()
async def xidach(ctx):
    await start_game(ctx)

async def start_game(ctx):
    view = View(timeout=None)
    view.add_item(JoinButton())

    if isinstance(ctx, discord.Interaction):
        await ctx.response.send_message("Tham gia chơi xì dách\nHiện có 0 người tham gia", view=view, ephemeral=False)
        message = await ctx.original_response()
    else:
        message = await ctx.send("Tham gia chơi xì dách\nHiện có 0 người tham gia", view=view)

    games[ctx.channel.id] = {
        "participants": set(),
        "message": message,
        "cards": {},
        "decisions": {},
        "start_message": None,
        "player_messages": {},
        "start_votes": set(),
        "game_id": None  # Khởi tạo game_id (sẽ được gán trong start_gameplay)
    }

@bot.event
async def on_ready():
    print(f"Bot đã sẵn sàng! Đăng nhập với tên: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Đã đồng bộ {len(synced)} lệnh slash.")
    except Exception as e:
        print(e)

# Chạy bot
bot.run(TOKEN)