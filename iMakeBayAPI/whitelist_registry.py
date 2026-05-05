#!/usr/bin/env python3
"""
iMak Trading Japan - eBay Item Specifics ホワイトリスト一元管理
2026-04-23 eBayフィルタ値検証から抽出した正規値リスト。
Claude API出力の自己修正ループで使用。

使い方:
  from whitelist_registry import validate_and_normalize, build_retry_feedback
  normalized, violations = validate_and_normalize(item_specifics, category="porter")
  if violations:
      feedback = build_retry_feedback(violations)
      # Claude API に再リクエスト
"""
import re

# ===================================================================
# カテゴリ別 ホワイトリスト定義
# ===================================================================
# 各エントリ:
#   values: 有効値リスト（完全一致）
#   strict: True=リスト外なら違反扱い, False=warning のみ
#   multi:  True=カンマ区切り複数値許可
#   normalize: {誤表記: 正規値} の自動修正マップ
#   regex:  正規表現（values の代わりにパターンマッチ）
# ===================================================================

WHITELISTS = {
    "tshirt": {
        "Brand": {
            "values": ["Uniqlo"],
            "strict": True,
            "normalize": {"UNIQLO": "Uniqlo", "UNIQLO UT": "Uniqlo", "Uniqlo UT": "Uniqlo"},
        },
        "Type": {
            "values": ["T-Shirt"],
            "strict": True,
            "normalize": {"Tee": "T-Shirt", "T Shirt": "T-Shirt"},
        },
        "Size Type": {"values": ["Regular", "Big & Tall", "Plus"], "strict": True},
        "Department": {
            "values": ["Men", "Women", "Unisex Adults", "Boys", "Girls", "Unisex Kids"],
            "strict": True,
        },
        "Theme": {
            "values": [
                "Anime", "Music", "Retro", "Cars", "Quotes", "Movie", "Hip Hop", "Rock",
                "Cartoon", "Comics", "Cosplay", "Video Games", "Funny", "Space",
                "Nature", "Sports", "Holiday", "Travel",
            ],
            "strict": True,
            "multi": True,
            "normalize": {"Anime & Manga": "Anime", "Manga": "Anime", "Games": "Video Games"},
        },
        "Style": {
            "values": ["Basic Tee", "Graphic Tee", "Polo Shirt", "Henley", "Tank Top"],
            "strict": True,
            "normalize": {"T-Shirt": "Graphic Tee", "Pullover": "Graphic Tee"},
        },
        "Closure": {
            "values": ["Pullover", "Button-Up", "Zipper", "None"],
            "strict": True,
        },
        "Pattern": {
            "values": ["Graphic Print", "Solid", "Floral", "Striped", "Plaid", "Camouflage", "Geometric"],
            "strict": False,
        },
        "Neckline": {
            "values": ["Crew Neck", "V-Neck", "Henley", "Scoop Neck", "Mock Neck"],
            "strict": True,
        },
        "Sleeve Length": {
            "values": ["Short Sleeve", "Long Sleeve", "Sleeveless", "3/4 Sleeve"],
            "strict": True,
        },
        "Material": {
            "values": ["Cotton", "100% Cotton", "Cotton Blend", "Polyester", "Rayon", "Linen", "Hemp"],
            "strict": False,
        },
        "Fit": {"values": ["Regular", "Slim", "Relaxed", "Oversized", "Athletic"], "strict": False},
        "Vintage": {"values": ["Yes", "No"], "strict": True},
        "Personalize": {"values": ["Yes", "No"], "strict": True},
        "Handmade": {"values": ["Yes", "No"], "strict": True},
    },

    "porter": {
        "Brand": {
            "values": ["Porter", "HEAD PORTER", "Yoshida & Co."],
            "strict": True,
            "normalize": {
                "PORTER": "Porter", "Porter Yoshida": "Porter",
                "Yoshida Porter": "Porter", "YOSHIDA PORTER": "Porter",
            },
        },
        "Style": {
            "values": [
                "Backpack", "Belt Bag & Fanny Pack", "Briefcase/Document Case",
                "Clutch", "Crossbody", "Duffle", "Gym Bag", "Laptop Bag",
                "Messenger Bag", "Saddle Bag", "Satchel", "Shoulder Bag",
                "Top Handle Bag", "Tote",
            ],
            "strict": True,
            "normalize": {
                "Tote Bag": "Tote", "Briefcase": "Briefcase/Document Case",
                "Document Case": "Briefcase/Document Case", "Belt Bag": "Belt Bag & Fanny Pack",
                "Fanny Pack": "Belt Bag & Fanny Pack", "Waist Bag": "Belt Bag & Fanny Pack",
            },
        },
        "Material": {
            "values": [
                "Acetate", "Acrylic", "Camel", "Canvas", "Cotton", "Cotton Blend",
                "Faux Leather", "Fur", "Hemp", "Leather", "Linen", "Nylon",
                "Patent Leather", "Plastic", "Polyester", "Polypropylene",
                "Polyurethane", "PVC", "Spandex", "Suede", "Vinyl", "Wool",
            ],
            "strict": True,
        },
        "Color": {
            "values": [
                "Beige", "Black", "Blue", "Brown", "Gold", "Gray", "Green",
                "Ivory", "Multicolor", "Orange", "Pink", "Purple", "Red",
                "Silver", "White", "Yellow",
            ],
            "strict": True,
            "normalize": {
                "Olive": "Green", "Khaki": "Green", "Navy": "Blue", "Cream": "Ivory",
                "Tan": "Beige", "Charcoal": "Gray", "Burgundy": "Red", "Wine": "Red",
                "Camo": "Multicolor",
            },
        },
        "Size": {
            "values": ["Mini", "Small", "Medium", "Large", "Extra Large"],
            "strict": True,
            "normalize": {"XL": "Extra Large", "S": "Small", "M": "Medium", "L": "Large", "XS": "Mini"},
        },
        "Department": {
            "values": ["Men", "Women", "Unisex Adults"],
            "strict": True,
        },
        "Occasion": {
            "values": ["Business", "Casual", "Formal", "Travel", "Workwear"],
            "strict": True,
            "multi": True,
        },
        "Closure": {
            "values": [
                "Buckle", "Button", "Catch Fastener", "Drawstring", "Hook & Loop",
                "Magnetic", "Push Lock", "Slide Closure", "Snap", "Tie", "Zip",
            ],
            "strict": True,
            "normalize": {"Zipper": "Zip", "Velcro": "Hook & Loop"},
        },
        "Pattern": {
            "values": [
                "Animal Print", "Camouflage", "Checkered", "Floral", "Geometric",
                "Herringbone", "Plaid", "Polka Dot", "Solid", "Striped",
            ],
            "strict": True,
        },
        "Handle Style": {
            "values": ["Crossbody Strap", "Double Handles", "Shoulder Strap", "Top Handle"],
            "strict": True,
            "normalize": {"Single Handle": "Top Handle"},
        },
        "Handle/Strap Material": {
            "values": [
                "Brass", "Camel", "Cotton", "Faux Leather", "Hemp", "Leather",
                "Linen", "Nickel", "Nylon", "Polyester", "Polyurethane", "Rubber",
                "Spandex", "Stainless Steel", "Straw",
            ],
            "strict": True,
        },
        "Theme": {
            "values": [
                "80s", "90s", "Animals", "Anime", "Army", "Art", "Beach", "Classic",
                "City", "Colorful", "Designer", "Hip Hop", "Holiday", "Metal",
                "Music", "Nature", "Outdoor", "Retro", "School", "Sports",
            ],
            "strict": False,  # Theme は3,605件空欄多数、厳格でなくてもOK
            "multi": True,
        },
        "Features": {
            "values": [
                "Adjustable Strap", "Anti-Theft", "Audio Pocket", "Bag Charm",
                "Bottle Pocket", "Convertible", "Credit Card", "Cross-Body Strap",
                "Detachable Strap", "Eco Friendly", "Folding", "Inner Dividers",
                "Inner Pockets", "Insulated", "Key Clip", "Laptop Sleeve/Protection",
                "Lightweight", "Limited Edition", "Lined", "Mobile Phone Pocket",
                "Organizer", "Outer Pockets", "Packable", "Padded", "Photo Holder",
                "Pockets", "Reflective", "Removable Pouch", "Reversible",
                "Stain-Resistant", "Water Resistant", "Waterproof", "Zip-Around",
            ],
            "strict": True,
            "multi": True,
            "normalize": {"Roomy": "", "Spacious": "Organizer"},
        },
        "Vintage": {"values": ["Yes", "No"], "strict": True},
        "Personalize": {"values": ["Yes", "No"], "strict": True},
        "Handmade": {"values": ["Yes", "No"], "strict": True},
    },

    "ichibankuji": {
        "Brand": {
            "values": ["Bandai", "BANPRESTO", "BANDAI NAMCO Entertainment", "FuRyu", "SEGA", "Taito", "Square Enix", "Capcom", "Konami", "Namco", "Good Smile Company", "KOTOBUKIYA", "Bushiroad", "Sanrio", "Pokémon Center", "Disney", "Hello Kitty", "Moomin", "Sailor Moon", "Rilakkuma", "San-X", "Onepiece", "Dragon Ball Z", "Yu-Gi-Oh!", "Nintendo", "Hasbro", "Shueisha", "Kadokawa"],
            "strict": True,
            "normalize": {"BANPREST": "BANPRESTO", "Banpresto": "BANPRESTO", "Pokemon Center": "Pokémon Center"},
        },
        "Theme": {
            "values": ["Advertising", "Angels", "Animals & Dinosaurs", "Animation", "Anime & Manga", "Art", "Cartoon & TV Characters", "Celebrity", "Circus", "Comic Book Heroes", "Fairy Tales", "Fantasy", "Film & TV", "Floral", "Food", "Food & Drink", "Football", "Historical Figures", "Military", "Motorcycles", "Music", "Mystical", "Olympics", "Racing Cars", "Romantic", "Seasonal", "Soccer", "Sport", "Transformers & Robots", "Transportation", "Video Games"],
            "strict": True,
            "normalize": {"Anime": "Anime & Manga", "Manga": "Anime & Manga"},  # cat 261055 では "Anime & Manga" が正規値
        },
        "Material": {
            "values": ["100% Cotton", "Acrylic", "Aluminum", "Beans", "Bronze", "Cardboard", "Clay", "Cloth", "Copper", "Cotton", "Cotton Blend", "Crystal", "Fabric", "Fabric/Canvas", "Felt", "Fleece", "Fur", "Glass", "Leather", "Metal", "Nylon", "Paper", "Plastic", "Platinum", "Plush", "Polyester", "Rose Gold", "Satin", "Shell", "Silver", "Stainless Steel", "Stone", "Straw", "Synthetic Fiber", "Tin", "Velvet", "Wood"],
            "strict": True,
            "normalize": {
                "PVC": "Plastic",  # eBay非フィルタ値、Plasticに統合
                "ABS": "Plastic",
                "PVC, ABS": "Plastic",
                "PVC, MABS": "Plastic",
                "Resin": "Plastic",  # Resinはeフィルタ値リストに無いのでPlasticに
            },
        },
        "Color": {
            "values": ["Beige", "Black", "Blue", "Brown", "Clear", "Gold", "Gray", "Green", "Multicolor", "Orange", "Pink", "Purple", "Red", "Silver", "White", "Yellow"],
            "strict": True,
            "normalize": {"Multi": "Multicolor", "Mixed": "Multicolor"},
        },
        "Country of Origin": {
            "values": ["Australia", "Azerbaijan", "Canada", "China", "Hong Kong", "Japan", "Malaysia", "Philippines", "Singapore", "Spain", "Thailand", "United Kingdom", "United States", "Vietnam"],
            "strict": True,
            "normalize": {"USA": "United States", "UK": "United Kingdom"},
        },
        "Language": {
            "values": ["Chinese", "English", "Japanese", "Korean", "Polish", "Russian"],
            "strict": True,
        },
        "Animation Studio": {
            "values": ["20th Century Animation", "Blue Sky Studios", "Bones Animation Studio", "Disney", "Illumination", "Kyoto Animation", "Nippon Animation", "Pixar", "Studio Pierrot", "Toei Animation", "Universal Animation Studios", "Warner Bros. Animation", "Wit Studio", "Does Not Apply"],
            "strict": True,
            "normalize": {
                # Suffix無しの正規値
                "Pixar Animation Studio": "Pixar",
                "Kyoto Animation Studio": "Kyoto Animation",
                "Studio Pierrot Animation Studio": "Studio Pierrot",
                "Wit Studio Animation Studio": "Wit Studio",
                "Pierrot": "Studio Pierrot",
                "Mappa": "Does Not Apply",  # eBayリストに無い
                "Mappa Animation Studio": "Does Not Apply",
                "Ufotable": "Does Not Apply",  # eBayリストに無い
                "Madhouse": "Does Not Apply",
                "A-1 Pictures": "Does Not Apply",
                "Sunrise": "Does Not Apply",
                "Trigger": "Does Not Apply",
            },
        },
        "Franchise": {
            "values": [
                "Akira", "Animal Crossing", "Arknights", "Attack on Titan", "Berserk",
                "Black Clover", "Bleach", "Cardcaptor Sakura", "Code Geass",
                "Death Note", "Demon Slayer: Kimetsu no Yaiba", "Digimon", "Disney",
                "Doraemon", "Dragon Ball", "Dragon Ball Z", "Fate/Stay Night",
                "Final Fantasy", "Fire Emblem", "Fullmetal Alchemist", "Gin Tama",
                "Godzilla", "Gundam", "Hatsune Miku", "Hello Kitty", "Hunter x Hunter",
                "Idolmaster", "JoJo's Bizarre Adventure", "Jujutsu Kaisen",
                "Kamen Rider", "Kingdom Hearts", "Kirby Adventures", "K-On!",
                "Konosuba", "Love Live!", "Macross/Robotech", "Madoka Magica",
                "Monster Hunter", "My Hero Academia", "Naruto", "Naruto Shippuden",
                "Neon Genesis Evangelion", "One Piece", "One Punch Man", "Persona",
                "Pokémon", "Re:Zero", "Sailor Moon", "Sanrio", "San-X",
                "Spider-Man", "Splatoon", "Star Wars", "Steins Gate", "Street Fighter",
                "Studio Ghibli", "Sumikko Gurashi", "Super Mario Bros.",
                "Sword Art Online", "That Time I Got Reincarnated As A Slime",
                "The Legend of Zelda", "The Quintessential Quintuplets", "Tokyo Ghoul",
                "Toy Story", "Transformers", "Urusei Yatsura", "Vocaloid",
                "Yo-Kai Watch", "Yu-Gi-Oh!", "Yu Yu Hakusho", "Marvel (MCU)",
            ],
            "strict": False,  # フィルタリスト外でも検索インデックスには載るので警告のみ
            "normalize": {
                "Pokemon": "Pokémon",  # é必須
                "Demon Slayer": "Demon Slayer: Kimetsu no Yaiba",
                "Kimetsu no Yaiba": "Demon Slayer: Kimetsu no Yaiba",
                "JoJo": "JoJo's Bizarre Adventure",
                "Jojo": "JoJo's Bizarre Adventure",
                "Yu-Gi-Oh": "Yu-Gi-Oh!",
                "Yugioh": "Yu-Gi-Oh!",
                "K-On": "K-On!",
                "JJK": "Jujutsu Kaisen",
                "MHA": "My Hero Academia",
                "OP": "One Piece",
                "Hunter X Hunter": "Hunter x Hunter",  # Franchise は小文字 x
                "Card Captor Sakura": "Cardcaptor Sakura",  # Franchise はスペース無し
                "Evangelion": "Neon Genesis Evangelion",
                "DBZ": "Dragon Ball Z",
                "FMA": "Fullmetal Alchemist",
            },
        },
        "TV Show": {
            "values": [
                "A Certain Scientific Railgun S", "Aladdin", "Angel", "Arpeggio Of Blue Steel",
                "Attack on Titan", "Berserk", "Black Clover", "Bleach", "Bungo Stray Dogs",
                "Card Captor Sakura", "Castle", "Code Geass", "Danganronpa",
                "Darling In The Franxx", "Death Note", "Demon Slayer: Kimetsu no Yaiba",
                "Digimon", "Digimon Adventure", "Digimon Tamers", "Doraemon", "Dororo",
                "Dragon Ball", "Fairy Tail", "Fate/Grand Order", "Fate/Stay Night",
                "Fate Apocrypha", "Final Fantasy", "Fire Force", "Fullmetal Alchemist",
                "Ghost in the Shell", "Gintama", "Girls und Panzer", "Goblin Slayer",
                "Gundam", "Higurashi When They Cry", "Hunter X Hunter", "Idolmaster",
                "Infinite Stratos", "Inuyasha", "Jojo's Bizarre Adventure", "Jujutsu Kaisen",
                "Kaguya-sama: Love is War", "Kamen Rider", "KanColle", "Kill la Kill",
                "Kirby", "Kizumonogatari", "Konosuba", "Kuroko's Basketball",
                "Love Live!", "Madoka Magica", "Magical Girl Lyrical Nanoha",
                "Monster Hunter", "My Hero Academia", "My Teen Romantic Comedy",
                "Naruto", "Naruto Shippuden", "Neon Genesis Evangelion", "Nier:Automata",
                "Okami", "One Piece", "One Punch Man", "Oreimo", "Pokémon",
                "Puella Magi Madoka Magica", "Rascal Does Not Dream of Bunny Girl Senpai",
                "Re:Zero", "Rent A Girlfriend", "Saekano: How To Raise A Boring Girlfriend",
                "Sailor Moon", "Spider-Man", "Splatoon", "Steins Gate",
                "Sword Art Online", "That Time I Got Reincarnated As A Slime",
                "The Quintessential Quintuplets", "To Heart", "Tokyo Ghoul",
                "Urusei Yatsura", "Yowamushi Pedal", "Yu-Gi-Oh!", "Yu-Gi-Oh! GX",
                "Yu-Gi-Oh! VRAINS", "Yu-Gi-Oh! Zexal", "Yu-Gi-Oh Duel Monsters",
                "Yu Yu Hakusho",
            ],
            "strict": False,
            "normalize": {
                "Pokemon": "Pokémon",
                "Demon Slayer": "Demon Slayer: Kimetsu no Yaiba",
                "JoJo's Bizarre Adventure": "Jojo's Bizarre Adventure",  # TV Show は小文字 j
                "JoJo": "Jojo's Bizarre Adventure",
                "Hunter x Hunter": "Hunter X Hunter",  # TV Show は大文字 X
                "Cardcaptor Sakura": "Card Captor Sakura",  # TV Show はスペース有
                "Evangelion": "Neon Genesis Evangelion",
            },
        },
        "Character": {
            # 主要キャラのホワイトリスト（一致時はフィルタヒット、外れたら自由文字列扱い）
            "values": [
                "All Might", "Izuku Midoriya", "Katsuki Bakugo", "Shoto Todoroki",
                "Ochaco Uraraka", "Tenya Iida", "Tsuyu Asui", "Eijiro Kirishima",
                "Denki Kaminari", "Fumikage Tokoyami", "Momo Yaoyorozu", "Mirio Togata",
                "Tamaki Amajiki", "Shota Aizawa", "Himiko Toga",
                "Tanjiro Kamado", "Nezuko Kamado", "Inosuke Hashibira", "Zenitsu Agatsuma",
                "Naruto Uzumaki", "Sasuke Uchiha", "Sakura Haruno",
                "Eren Jaeger", "Mikasa Ackerman", "Levi Ackerman", "Armin Arlert", "Hanji Zoe",
                "Sailor Moon", "Sailor Mercury", "Sailor Mars", "Sailor Jupiter", "Sailor Venus",
                "Robin", "Egghead", "Nefertari Vivi",
                "Hatsune Miku", "Asuka Langley Sohryu", "Asuna Yuuki", "Kirigaya Kazuto",
                "Saber", "Archer", "Rin Tohsaka", "Illyasviel von Einzbern",
                "Light Yagami", "L", "Ryuk",
                "Edward Elric", "Lucy Heartfilia", "Sakura Kinomoto",
                "Conan", "Conan Edogawa", "Ran Mouri", "Shinichi Kudo",
                "Mickey Mouse", "Donald Duck", "Goofy", "Stitch", "Totoro",
                "Snoopy", "Snorlax", "Cinnamoroll", "My Melody", "Pochacco",
                "Hello Kitty", "Rilakkuma", "Gudetama", "Badtz Maru", "Keroppi",
                "Spider-Man", "Iron Man", "Wolverine",
            ],
            "strict": False,  # ホワイトリスト外でも記入（検索インデックス用）
            "normalize": {
                "Goku": "Goku",  # ホワイトリスト無しでもそのまま記入
                "Vegeta": "Vegeta",
                "Luffy": "Luffy",
                "Tanjiro": "Tanjiro Kamado",
                "Nezuko": "Nezuko Kamado",
                "Naruto": "Naruto Uzumaki",
                "Sasuke": "Sasuke Uchiha",
                "Eren": "Eren Jaeger",
                "Mikasa": "Mikasa Ackerman",
                "Levi": "Levi Ackerman",
                "Deku": "Izuku Midoriya",
                "Bakugo": "Katsuki Bakugo",
                "Bakugou": "Katsuki Bakugo",
                "Todoroki": "Shoto Todoroki",
                "Miku": "Hatsune Miku",
            },
        },
        "Vintage": {"values": ["Yes", "No"], "strict": True},
        "Signed": {"values": ["Yes", "No"], "strict": True},
        "Original/Licensed Reproduction": {
            "values": ["Original", "Licensed Reproduction", "Unauthorized Reproduction"],
            "strict": True,
        },
    },


    "tomica": {
        "Brand": {
            "values": ["Tomica", "Takara", "TOMY", "Tomytec", "Takara Tomy"],
            "strict": True,
            "normalize": {
                "TOMICA": "Tomica",
                "tomica": "Tomica",
                "Tomy": "TOMY",
                "Takara-Tomy": "Takara Tomy",
                "TakaraTomy": "Takara Tomy",
            },
        },
        "Vehicle Type": {
            "values": [
                "Ambulance", "Bus", "Car", "Car Transporter", "Chase Car",
                "Commercial Vehicle", "Container", "Delivery Truck", "Demolition Derby",
                "Dump Truck", "Dump Truck/Tipper", "Emergency Vehicle", "Fire Vehicle",
                "Garbage Truck", "Golf Car", "Hearse", "Hot Dog Truck", "Ice Cream Truck",
                "Limousine", "Low-Loader", "Monster Truck", "Motorhome/Camper",
                "Pickup Truck", "Police Vehicle", "School Bus", "Tanker Truck",
                "Tow Truck", "Tractor Trailer/Semi", "Tractor Unit", "Trailer",
                "Truck", "Truck/Lorry", "Van",
            ],
            "strict": True,
            "normalize": {
                "Sedan": "Car", "SUV": "Car", "Sports Car": "Car", "Race Car": "Car",
                "Wagon": "Car", "Coupe": "Car", "Lorry": "Truck/Lorry",
                "Police Car": "Police Vehicle", "Fire Truck": "Fire Vehicle",
                "Camper": "Motorhome/Camper", "RV": "Motorhome/Camper",
                "Semi": "Tractor Trailer/Semi", "Semi Truck": "Tractor Trailer/Semi",
                "Tipper": "Dump Truck/Tipper",
            },
        },
        "Vehicle Make": {
            "values": [
                "Abarth", "AC", "Acura", "Airbus", "Alfa Romeo", "Alpine", "AMC",
                "Aston Martin", "Audi", "Austin", "Bentley", "BMW", "Boeing", "Bugatti",
                "Buick", "Cadillac", "CAT", "Chevrolet", "Citroën", "Daewoo",
                "Daihatsu", "Daimler", "Datsun", "DeLorean", "DeTomaso", "Dodge",
                "Eagle", "Ferrari", "Fiat", "Ford", "Ghia", "GMC", "Honda",
                "Hot Wheels", "Hudson", "Hummer", "Hyundai", "Imperial", "Indian",
                "IndyCar", "Infiniti", "International Harvester", "Isuzu", "Jaguar",
                "JCB", "Jeep", "John Deere", "Kawasaki", "Koenigsegg", "Komatsu",
                "Lamborghini", "Lancia", "Land Rover", "Lexus", "Lincoln", "Lockheed",
                "Lotus", "Mack", "MAN", "Marvel", "Maserati", "Matchbox", "Mazda",
                "McLaren", "Mercedes-Benz", "Mini Cooper", "Mitsubishi", "Morgan",
                "Morris", "Mustang", "Nissan", "Oldsmobile", "Opel", "Packard",
                "Panther", "Peterbilt", "Peugeot", "Plymouth", "Pontiac", "Porsche",
                "PUMA", "Range Rover", "Renault", "Rolls-Royce", "Saab", "Scania",
                "SEAT", "Shelby", "Smart", "Subaru", "Suzuki", "Tesla", "Toyota",
                "Unimog", "Volkswagen", "Volvo", "Willys", "Yamaha",
            ],
            "strict": True,  # eBay公式enum、外れたら警告
            "normalize": {
                "TOYOTA": "Toyota",
                "HONDA": "Honda",
                "NISSAN": "Nissan",
                "Mercedes Benz": "Mercedes-Benz",
                "Mercedes": "Mercedes-Benz",
                "VW": "Volkswagen",
                "Chevy": "Chevrolet",
                "Citroen": "Citroën",  # アクサン付きが正規値
                "Mini": "Mini Cooper",
                "Hino": "Isuzu",  # eBayにHinoなし→Isuzu系統に近い、または保留
            },
        },
        "Material": {
            "values": ["ABS", "Cast Iron", "Diecast", "Metal", "Plastic", "Pressed Steel", "Resin", "Tin", "White Metal", "Wood", "Zamak"],
            "strict": True,
            "normalize": {
                "Die-cast": "Diecast",
                "Die Cast": "Diecast",
                "Diecast Metal": "Diecast",
                "Steel": "Pressed Steel",
                "Stainless Steel": "Metal",
                "Aluminum": "Metal",
            },
        },
        "Scale": {
            "values": ["1:6", "1:8", "1:9", "1:10", "1:12", "1:16", "1:18", "1:20", "1:22", "1:24", "1:25", "1:26", "1:32", "1:34", "1:35", "1:40", "1:43", "1:48", "1:50", "1:53", "1:55", "1:60", "1:64", "1:66", "1:72", "1:76", "1:80", "1:87", "1:160", "1:200", "1:400", "1:500"],
            "strict": True,
            "normalize": {
                "1:65": "1:64",  # eBay非フィルタ値、1:64 (14K件)に正規化（フィルタヒット優先）。元スケール表記はDescription側に記載
                "1/64": "1:64",
                "1/60": "1:60",
                "1/65": "1:64",
                "1/66": "1:66",
                "1/43": "1:43",
            },
        },
        "Color": {
            "values": ["Black", "Blue", "Brown", "Clear", "Gold", "Gray", "Green", "Multi-Color", "Orange", "Pink", "Purple", "Red", "Silver", "White", "Yellow"],
            "strict": True,
            "normalize": {
                "Multicolor": "Multi-Color",  # Tomica系は ハイフン付き "Multi-Color"
                "Beige": "Brown",  # Tomica enumに Beige無し → Brown最も近い
                "Ivory": "White",
                "Olive": "Green",
                "Khaki": "Green",
                "Navy": "Blue",
                "Cream": "White",
                "Tan": "Brown",
                "Charcoal": "Gray",
            },
        },
        "Character Family": {
            "values": [
                "Batman", "Captain America", "Cars", "ChoroQ", "Curious George",
                "DC Universe", "Disney Pixar Cars", "Disney Princess", "Doraemon",
                "Dukes of Hazzard", "Emergency!", "Evangelion", "Finding Nemo",
                "Gundam", "Harry Potter", "Hello Kitty", "Incredible Hulk",
                "Iron Man", "James Bond", "K-On!", "Macross", "Mad Max",
                "Marvel Universe", "Mickey Mouse & Friends", "Monsters Inc.",
                "Muppets", "Nightmare Before Christmas", "One Piece", "Peanuts Gang",
                "Penny Racers", "Phineas & Ferb", "Pirates of the Caribbean",
                "Pokemon", "Ratatouille", "Sesame Street", "Smokey and the Bandit",
                "Speed Racer", "Spider-Man", "SpongeBob SquarePants", "Star Wars",
                "Super Mario Bros.", "Teenage Mutant Ninja Turtles",
                "The Fast and the Furious", "The Incredibles", "Thomas & Friends",
                "Thor", "Toy Story", "Transformers", "Universal Monsters",
                "Winnie the Pooh & Friends", "Yu-Gi-Oh!",
            ],
            "strict": True,  # 51値enum、リスト外は使用禁止
            "normalize": {
                "Cars (Pixar)": "Disney Pixar Cars",
                "Pixar Cars": "Disney Pixar Cars",
                "Pokémon": "Pokemon",  # Character Family は é なし
                "Mickey Mouse": "Mickey Mouse & Friends",
                "Thomas the Tank Engine": "Thomas & Friends",
                "Marvel": "Marvel Universe",
                "DC": "DC Universe",
                "Snoopy": "Peanuts Gang",
                "Peanuts": "Peanuts Gang",
                "Fast and Furious": "The Fast and the Furious",
                "Fast & Furious": "The Fast and the Furious",
                "Mario": "Super Mario Bros.",
                "TMNT": "Teenage Mutant Ninja Turtles",
                "Winnie the Pooh": "Winnie the Pooh & Friends",
                "Pooh": "Winnie the Pooh & Friends",
            },
        },
        "Series": {
            "values": [
                "Tomica Common Series", "Tomica Domestic Series",
                "Tomica Foreign Series", "Tomica Limited Series",
                "Toyota Land Cruiser", "Fast & Furious",
            ],
            "strict": True,
            "normalize": {
                "Tomica": "Tomica Common Series",
                "TLV": "Tomica Limited Series",
                "Tomica Limited Vintage": "Tomica Limited Series",
                "Common": "Tomica Common Series",
                "Domestic": "Tomica Domestic Series",
                "Foreign": "Tomica Foreign Series",
            },
        },
        "Features": {
            "values": [
                "Advertising Specimen", "Built From Scratch", "Chase", "Flash Drive",
                "GDR Vehicle", "Limited Edition", "Personal Number Plate",
                "Special Edition", "Unglazed", "Unopened Box", "With Case", "With Stand",
            ],
            "strict": True,
            "multi": True,
            "normalize": {
                "New In Box": "Unopened Box",
                "NIB": "Unopened Box",
                "Sealed": "Unopened Box",
                "Mint In Box": "Unopened Box",
                "MIB": "Unopened Box",
                "Limited": "Limited Edition",
                "Special": "Special Edition",
            },
        },
        "Country/Region of Manufacture": {
            "values": ["Japan", "China", "Vietnam", "Thailand", "Hong Kong", "Taiwan", "Malaysia", "Indonesia", "Does not apply"],
            "strict": True,
            "normalize": {"USA": "Does not apply", "United States": "Does not apply"},  # Tomicaは基本Japan/China/Vietnam
        },
        "Recommended Age Range": {
            "values": ["3+", "5+", "8+", "12+", "14+", "17+"],
            "strict": False,
            "normalize": {"3 years and up": "3+", "+3": "3+", "Ages 3+": "3+"},
        },
        "Year of Manufacture": {
            "regex": r"^(19[5-9]\d|20[0-2]\d)$",  # 4桁西暦 1950-2029
            "strict": True,
            "normalize_func": "extract_year",
        },
        "Theme": {
            "values": ["Cars", "Cartoon", "Movie", "Anime", "Sports", "Military", "Vintage"],
            "strict": False,
        },
        "Modified Item": {"values": ["Yes", "No"], "strict": True},
        "Customized": {"values": ["Yes", "No"], "strict": True},
        "Autographed": {"values": ["Yes", "No"], "strict": True},
        "Vintage": {"values": ["Yes", "No"], "strict": True},
        "Gender": {
            "values": ["Boys", "Girls", "Boys & Girls", "Unisex"],
            "strict": True,
            "normalize": {"Boys and Girls": "Boys & Girls", "Both": "Boys & Girls"},
        },
    },

    "reel": {
        "Brand": {
            "values": [
                "Daiwa", "Shimano", "Abu Garcia", "Penn", "Okuma", "Lew's",
                "Megabass", "13 Fishing", "Tackle Industries", "Quantum",
            ],
            "strict": False,
        },
        "Reel Type": {
            "values": ["Baitcasting", "Spinning", "Conventional", "Fly", "Spincast", "Trolling"],
            "strict": True,
            "normalize": {"Baitcast": "Baitcasting", "Bait Casting": "Baitcasting"},
        },
        "Hand Retrieve": {
            "values": ["Left", "Right", "Right/Left Interchangeable"],
            "strict": True,
            "normalize": {"L": "Left", "R": "Right", "Both": "Right/Left Interchangeable"},
        },
        "Material": {
            "values": [
                "Aluminum", "Alloy", "Carbon Fiber", "Graphite", "Plastic",
                "Stainless Steel", "Titanium", "Wood", "Composite",
            ],
            "strict": True,
            "normalize": {"Aluminum Alloy": "Aluminum"},
        },
        "Ball Bearings": {
            "regex": r"^\d+$",  # 整数のみ（"6+1" 等禁止）
            "strict": True,
            "normalize_func": "extract_integer",  # "6+1" → "6"
            "plausibility_range_int": (1, 20),  # リールBB数は1-20が妥当
        },
        "Item Weight": {
            "regex": r"^\d+\.?\d*\s*g$",  # "195 g" 形式
            "strict": False,
            "plausibility_range_numeric": (50, 2000),  # リール重量 50g-2kg（ルアー混入検出: 9.7g等）
            "extract_unit": "g",
        },
        "Maximum Drag": {
            "regex": r"^\d+\.?\d*\s*(kg|lb)$",  # "5 kg" or "11 lb"
            "strict": False,
            "plausibility_range_numeric": (1, 50),  # リールドラグ 1kg-50kg
            "extract_unit": "kg",
        },
        "Gear Ratio": {
            "regex": r"^\d+\.?\d*:\d+$",  # "6.2:1" 形式
            "strict": False,
            "plausibility_ratio_range": (3.0, 10.0),  # ギア比 3:1-10:1
        },
        "Features": {
            # eBay Features フィールドは65文字制限。超過すると Add 失敗
            # 機能カテゴリ標準値（自由文字列許可、超過したら自動truncate）
            "max_length": 65,
            "multi": True,
            "strict": False,  # eBay側で値enumなし、自由
        },
        "Country/Region of Manufacture": {
            # 推測禁止ルール: タグ/公式から確証取れた国 or "Does not apply"
            "values": [
                "Japan", "China", "Taiwan", "Vietnam", "Thailand", "Malaysia",
                "Indonesia", "Philippines", "United States", "Does not apply",
            ],
            "strict": True,
        },
    },
}


# ===================================================================
# 正規化ヘルパー（regexマッチ時の事前加工）
# ===================================================================
def _extract_integer(val: str) -> str:
    """'6+1' → '6' のような整数抽出"""
    m = re.match(r'^(\d+)', str(val).strip())
    return m.group(1) if m else ""


def _extract_year(val: str) -> str:
    """'1977' / '1977年' / 'c.1977' から4桁西暦抽出"""
    m = re.search(r'(19[5-9]\d|20[0-2]\d)', str(val))
    return m.group(1) if m else ""


_NORMALIZE_FUNCS = {
    "extract_integer": _extract_integer,
    "extract_year": _extract_year,
}


# ===================================================================
# メイン検証関数
# ===================================================================
def validate_and_normalize(specs: dict, category: str) -> tuple[dict, list]:
    """item_specifics を検証し、可能なら正規化する。

    Args:
        specs: {field: value} の dict
        category: "tshirt" / "porter" / "reel" 等

    Returns:
        (normalized_specs, violations)
        violations: [(field, original_value, expected, reason), ...]
    """
    if category not in WHITELISTS:
        return specs, []

    rules = WHITELISTS[category]
    normalized = dict(specs)
    violations = []

    for field, rule in rules.items():
        if field not in specs:
            continue
        val = specs[field]
        if not val or val == "":
            continue
        val_str = str(val).strip()

        # 0. max_length チェック (eBay各フィールド文字数制限)
        max_len = rule.get("max_length")

        # 1. regex ルール (Ball Bearings 等)
        if "regex" in rule:
            # 先に normalize_func で前処理
            if "normalize_func" in rule:
                func = _NORMALIZE_FUNCS.get(rule["normalize_func"])
                if func:
                    normalized_val = func(val_str)
                    if normalized_val and normalized_val != val_str:
                        normalized[field] = normalized_val
                        val_str = normalized_val
            if not re.match(rule["regex"], val_str):
                violations.append((field, val, rule["regex"], "regex_mismatch"))
                continue
            # 妥当性レンジチェック（プログラマブル安全装置）
            if "plausibility_range_int" in rule:
                lo, hi = rule["plausibility_range_int"]
                try:
                    n = int(re.search(r'\d+', val_str).group(0))
                    if not (lo <= n <= hi):
                        violations.append((field, val, f"妥当範囲 {lo}-{hi}", f"範囲外({n}) - 異種商品混入の可能性"))
                except Exception:
                    pass
            elif "plausibility_range_numeric" in rule:
                lo, hi = rule["plausibility_range_numeric"]
                try:
                    n = float(re.search(r'\d+\.?\d*', val_str).group(0))
                    if not (lo <= n <= hi):
                        violations.append((field, val, f"妥当範囲 {lo}-{hi}", f"範囲外({n}) - 異種商品混入の可能性"))
                except Exception:
                    pass
            elif "plausibility_ratio_range" in rule:
                lo, hi = rule["plausibility_ratio_range"]
                try:
                    m = re.search(r'(\d+\.?\d*):(\d+)', val_str)
                    if m:
                        n = float(m.group(1)) / float(m.group(2))
                        if not (lo <= n <= hi):
                            violations.append((field, val, f"妥当範囲 {lo}:1-{hi}:1", f"範囲外 - 異種商品混入の可能性"))
                except Exception:
                    pass
            continue

        # 2. multi=True → カンマ区切り分解検証
        if rule.get("multi"):
            parts = [p.strip() for p in val_str.split(",")]
            normalize_map = rule.get("normalize", {})
            accepted, rejected = [], []
            for p in parts:
                if not p:
                    continue
                normalized_p = normalize_map.get(p, p)
                if not normalized_p:
                    continue
                if "values" in rule:
                    if normalized_p in rule["values"]:
                        if normalized_p not in accepted:
                            accepted.append(normalized_p)
                    else:
                        rejected.append(p)
                        if not rule.get("strict"):
                            accepted.append(p)
                else:
                    accepted.append(normalized_p)
            joined = ", ".join(accepted)
            # max_length 超過なら末尾から削る（eBay文字数制限対策）
            if max_len and len(joined) > max_len:
                trimmed = []
                for item in accepted:
                    candidate = ", ".join(trimmed + [item])
                    if len(candidate) <= max_len:
                        trimmed.append(item)
                joined = ", ".join(trimmed)
                violations.append((
                    field, val,
                    f"max_length={max_len}文字以内",
                    f"{len(', '.join(accepted))}文字超過 → '{joined}' に短縮",
                ))
            normalized[field] = joined
            if rejected and rule.get("strict"):
                violations.append((
                    field, val,
                    f"有効値: {rule['values']}",
                    f"無効な値含む: {rejected}",
                ))
            continue

        # 3. 単一値
        normalize_map = rule.get("normalize", {})
        normalized_val = normalize_map.get(val_str, val_str)
        if "values" in rule:
            if normalized_val not in rule["values"]:
                if rule.get("strict"):
                    violations.append((
                        field, val,
                        f"有効値: {rule['values']}",
                        "not_in_whitelist",
                    ))
                normalized[field] = normalized_val  # 正規化は試みる
            else:
                normalized[field] = normalized_val
        else:
            normalized[field] = normalized_val

        # max_length チェック（単一値・values無し系も対象）
        if max_len and len(str(normalized.get(field, ""))) > max_len:
            current = str(normalized.get(field, ""))
            violations.append((
                field, val,
                f"max_length={max_len}文字以内",
                f"{len(current)}文字超過",
            ))

    return normalized, violations


# ===================================================================
# Claude API 再リクエスト用フィードバック生成
# ===================================================================
def build_retry_feedback(violations: list) -> str:
    """違反リストから Claude 向け再指示テキストを生成"""
    if not violations:
        return ""
    lines = [
        "前回の出力に以下のItem Specifics違反がありました。eBay公式フィルタ値に修正して再出力してください:",
        "",
    ]
    for field, orig, expected, reason in violations:
        lines.append(f"【{field}】")
        lines.append(f"  ❌ 出力値: \"{orig}\"")
        lines.append(f"  ✅ {expected}")
        lines.append(f"  理由: {reason}")
        lines.append("")
    lines.append("上記を修正し、他のフィールドはそのまま維持してJSON形式で再出力してください。")
    return "\n".join(lines)


# ===================================================================
# スタンドアロン動作確認
# ===================================================================
if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    # テストケース
    test_porter = {
        "Brand": "UNIQLO",  # 違反（Porterカテゴリにない）
        "Style": "Tote Bag",  # 正規化 → "Tote"
        "Color": "Olive",  # 正規化 → "Green"
        "Size": "XL",  # 正規化 → "Extra Large"
        "Material": "Nylon",  # OK
    }
    normalized, viol = validate_and_normalize(test_porter, "porter")
    print("=== Porter テスト ===")
    print("Normalized:", normalized)
    print("Violations:", viol)
    print()
    print("=== フィードバック ===")
    print(build_retry_feedback(viol))
