"""Generate demo seed data for Echo Graph.

Output: data/seed.json

Data structure follows readme.md:
- Author: id, nationality, originalName, Name_CN, Name_EN, birthYear,
  deathYear, primaryLanguage (ISO 639-1), bio, createdAt, updatedAt
- Work: id, language (ISO 639-1), originalTitle, Title_CN, Title_EN,
  publicationYear, creationYear, summary, createdAt, updatedAt
- Relations: (Work)-[:AUTHORED_BY]->(Author), (Work)-[:ECHO]->(Work)
  ECHO props: evidence (正文摘抄片段), note (备注)

IMPORTANT: All data is SYNTHETIC DEMO DATA. Author/work metadata roughly
follows literary history, but every ECHO edge and its evidence text is
fabricated for demonstration and must NOT be treated as scholarly fact.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# id -> (originalName, Name_CN, Name_EN, birthYear, deathYear, nationality, primaryLanguage)
AUTHORS: dict[str, tuple] = {
    "homer": ("Homer", "荷马", "Homer", -800, -700, "古希腊", "el"),
    "virgil": ("Publius Vergilius Maro", "维吉尔", "Virgil", -70, -19, "古罗马", "la"),
    "dante": ("Dante Alighieri", "但丁", "Dante", 1265, 1321, "意大利", "it"),
    "chaucer": ("Geoffrey Chaucer", "乔叟", "Chaucer", 1343, 1400, "英国", "en"),
    "quyuan": ("屈原", "屈原", "Qu Yuan", -340, -278, "中国", "zh"),
    "dufu": ("杜甫", "杜甫", "Du Fu", 712, 770, "中国", "zh"),
    "libai": ("李白", "李白", "Li Bai", 701, 762, "中国", "zh"),
    "shakespeare": ("William Shakespeare", "莎士比亚", "Shakespeare", 1564, 1616, "英国", "en"),
    "cervantes": ("Miguel de Cervantes Saavedra", "塞万提斯", "Cervantes", 1547, 1616, "西班牙", "es"),
    "shikibu": ("紫式部", "紫式部", "Murasaki Shikibu", 973, 1014, "日本", "ja"),
    "caoxueqin": ("曹雪芹", "曹雪芹", "Cao Xueqin", 1715, 1763, "中国", "zh"),
    "goethe": ("Johann Wolfgang von Goethe", "歌德", "Goethe", 1749, 1832, "德国", "de"),
    "balzac": ("Honoré de Balzac", "巴尔扎克", "Balzac", 1799, 1850, "法国", "fr"),
    "poe": ("Edgar Allan Poe", "爱伦·坡", "Edgar Allan Poe", 1809, 1849, "美国", "en"),
    "gogol": ("Николай Васильевич Гоголь", "果戈里", "Gogol", 1809, 1852, "俄国", "ru"),
    "dickens": ("Charles Dickens", "狄更斯", "Dickens", 1812, 1870, "英国", "en"),
    "dostoevsky": ("Фёдор Михайлович Достоевский", "陀思妥耶夫斯基", "Dostoevsky", 1821, 1881, "俄国", "ru"),
    "flaubert": ("Gustave Flaubert", "福楼拜", "Flaubert", 1821, 1880, "法国", "fr"),
    "baudelaire": ("Charles Baudelaire", "波德莱尔", "Baudelaire", 1821, 1867, "法国", "fr"),
    "tolstoy": ("Лев Николаевич Толстой", "托尔斯泰", "Tolstoy", 1828, 1910, "俄国", "ru"),
    "ibsen": ("Henrik Ibsen", "易卜生", "Ibsen", 1828, 1906, "挪威", "no"),
    "dickinson": ("Emily Dickinson", "狄金森", "Dickinson", 1830, 1886, "美国", "en"),
    "chekhov": ("Антон Павлович Чехов", "契诃夫", "Chekhov", 1860, 1904, "俄国", "ru"),
    "wilde": ("Oscar Wilde", "王尔德", "Wilde", 1854, 1900, "爱尔兰", "en"),
    "tagore": ("রবীন্দ্রনাথ ঠাকুর", "泰戈尔", "Tagore", 1861, 1941, "印度", "bn"),
    "lu_xun": ("周树人", "鲁迅", "Lu Xun", 1881, 1936, "中国", "zh"),
    "soseki": ("夏目漱石", "夏目漱石", "Natsume Soseki", 1867, 1916, "日本", "ja"),
    "james": ("Henry James", "亨利·詹姆斯", "Henry James", 1843, 1916, "美国", "en"),
    "proust": ("Marcel Proust", "普鲁斯特", "Proust", 1871, 1922, "法国", "fr"),
    "joyce": ("James Joyce", "乔伊斯", "Joyce", 1882, 1941, "爱尔兰", "en"),
    "kafka": ("Franz Kafka", "卡夫卡", "Kafka", 1883, 1924, "奥地利", "de"),
    "woolf": ("Virginia Woolf", "伍尔夫", "Woolf", 1882, 1941, "英国", "en"),
    "faulkner": ("William Faulkner", "福克纳", "Faulkner", 1897, 1962, "美国", "en"),
    "hemingway": ("Ernest Hemingway", "海明威", "Hemingway", 1899, 1961, "美国", "en"),
    "borges": ("Jorge Luis Borges", "博尔赫斯", "Borges", 1899, 1986, "阿根廷", "es"),
    "camus": ("Albert Camus", "加缪", "Camus", 1913, 1960, "法国", "fr"),
    "orwell": ("George Orwell", "奥威尔", "Orwell", 1903, 1950, "英国", "en"),
    "nabokov": ("Vladimir Nabokov", "纳博科夫", "Nabokov", 1899, 1977, "俄裔美籍", "en"),
    "kawabata": ("川端康成", "川端康成", "Kawabata", 1899, 1972, "日本", "ja"),
    "laoshe": ("舒庆春", "老舍", "Lao She", 1899, 1966, "中国", "zh"),
    "zhangailing": ("张爱玲", "张爱玲", "Eileen Chang", 1920, 1995, "中国", "zh"),
    "shencongwen": ("沈从文", "沈从文", "Shen Congwen", 1902, 1988, "中国", "zh"),
    "rulfo": ("Juan Rulfo", "鲁尔福", "Rulfo", 1917, 1986, "墨西哥", "es"),
    "marquez": ("Gabriel García Márquez", "马尔克斯", "Márquez", 1927, 2014, "哥伦比亚", "es"),
    "murakami": ("村上春樹", "村上春树", "Murakami", 1949, None, "日本", "ja"),
    "yuhua": ("余华", "余华", "Yu Hua", 1960, None, "中国", "zh"),
    "moyan": ("管谟业", "莫言", "Mo Yan", 1955, None, "中国", "zh"),
    "eliot": ("Thomas Stearns Eliot", "艾略特", "T. S. Eliot", 1888, 1965, "英裔美籍", "en"),
    "hessen": ("Hermann Hesse", "黑塞", "Hesse", 1877, 1962, "德裔瑞士", "de"),
    "rimbaud": ("Arthur Rimbaud", "兰波", "Rimbaud", 1854, 1891, "法国", "fr"),
    "christie": ("Agatha Mary Clarissa Christie", "阿加莎·克里斯蒂", "Agatha Christie", 1890, 1976, "英国", "en"),
}

# author_id -> list of (work_id, Title_CN, Title_EN, originalTitle, year)
# 年份 >= 1700 记入 publicationYear,< 1700 记入 creationYear(演示规则)
WORKS: dict[str, list[tuple]] = {
    "homer": [
        ("iliad", "伊利亚特", "Iliad", "Ἰλιάς", -750),
        ("odyssey", "奥德赛", "Odyssey", "Ὀδύσσεια", -700),
    ],
    "virgil": [
        ("aeneid", "埃涅阿斯纪", "Aeneid", "Aeneis", -19),
        ("georgics", "农事诗", "Georgics", "Georgica", -29),
    ],
    "dante": [
        ("divine_comedy", "神曲", "The Divine Comedy", "La Divina Commedia", 1320),
        ("vita_nuova", "新生", "La Vita Nuova", "La Vita Nuova", 1295),
    ],
    "chaucer": [
        ("canterbury_tales", "坎特伯雷故事集", "The Canterbury Tales", "The Canterbury Tales", 1400),
        ("troilus", "特洛伊罗斯与克瑞西达", "Troilus and Criseyde", "Troilus and Criseyde", 1385),
    ],
    "quyuan": [
        ("lisao", "离骚", "Li Sao", "離騷", -300),
        ("jiu_ge", "九歌", "Nine Songs", "九歌", -300),
    ],
    "dufu": [
        ("sanli_sanbie", "三吏三别", "Three Officials and Three Partings", "三吏三別", 759),
        ("qiuxing_bashou", "秋兴八首", "Eight Autumn Meditations", "秋興八首", 766),
    ],
    "libai": [
        ("jiang_jin_jiu", "将进酒", "Invitation to Wine", "將進酒", 752),
        ("jing_ye_si", "静夜思", "Quiet Night Thought", "靜夜思", 726),
    ],
    "shakespeare": [
        ("hamlet", "哈姆雷特", "Hamlet", "The Tragedy of Hamlet, Prince of Denmark", 1603),
        ("king_lear", "李尔王", "King Lear", "The Tragedy of King Lear", 1606),
        ("macbeth", "麦克白", "Macbeth", "The Tragedy of Macbeth", 1606),
    ],
    "cervantes": [
        ("don_quixote", "堂吉诃德", "Don Quixote", "El ingenioso hidalgo don Quijote de la Mancha", 1615),
        ("exemplary_novels", "惩恶扬善故事集", "Novelas ejemplares", "Novelas ejemplares", 1613),
    ],
    "shikibu": [
        ("genji", "源氏物语", "The Tale of Genji", "源氏物語", 1010),
        ("shikibu_diary", "紫式部日记", "The Diary of Lady Murasaki", "紫式部日記", 1010),
    ],
    "caoxueqin": [
        ("hongloumeng", "红楼梦", "Dream of the Red Chamber", "紅樓夢", 1791),
    ],
    "goethe": [
        ("faust", "浮士德", "Faust", "Faust. Eine Tragödie", 1831),
        ("werther", "少年维特的烦恼", "The Sorrows of Young Werther", "Die Leiden des jungen Werthers", 1774),
    ],
    "balzac": [
        ("pere_goriot", "高老头", "Old Goriot", "Le Père Goriot", 1835),
        ("comedie_humaine", "人间喜剧", "La Comédie Humaine", "La Comédie humaine", 1850),
    ],
    "poe": [
        ("raven", "乌鸦", "The Raven", "The Raven", 1845),
        ("rue_morgue", "莫格街凶杀案", "The Murders in the Rue Morgue", "The Murders in the Rue Morgue", 1841),
    ],
    "gogol": [
        ("overcoat", "外套", "The Overcoat", "Шинель", 1842),
        ("diary_madman", "狂人日记", "Diary of a Madman", "Записки сумасшедшего", 1835),
    ],
    "dickens": [
        ("oliver_twist", "雾都孤儿", "Oliver Twist", "Oliver Twist; or, the Parish Boy's Progress", 1838),
        ("david_copperfield", "大卫·科波菲尔", "David Copperfield", "The Personal History of David Copperfield", 1850),
    ],
    "dostoevsky": [
        ("notes_underground", "地下室手记", "Notes from Underground", "Записки из подполья", 1864),
        ("crime_punishment", "罪与罚", "Crime and Punishment", "Преступление и наказание", 1866),
    ],
    "flaubert": [
        ("madame_bovary", "包法利夫人", "Madame Bovary", "Madame Bovary", 1857),
        ("education_sentimentale", "情感教育", "Sentimental Education", "L'Éducation sentimentale", 1869),
    ],
    "baudelaire": [
        ("fleurs_du_mal", "恶之花", "Les Fleurs du Mal", "Les Fleurs du mal", 1857),
        ("paris_spleen", "巴黎的忧郁", "Le Spleen de Paris", "Le Spleen de Paris", 1869),
    ],
    "tolstoy": [
        ("war_peace", "战争与和平", "War and Peace", "Война и мир", 1869),
        ("anna_karenina", "安娜·卡列尼娜", "Anna Karenina", "Анна Каренина", 1877),
    ],
    "ibsen": [
        ("doll_house", "玩偶之家", "A Doll's House", "Et dukkehjem", 1879),
        ("ghosts", "群鬼", "Ghosts", "Gengangere", 1881),
    ],
    "dickinson": [
        ("because_i_could_not_stop", "因为我不能停步等待死神", "Because I Could Not Stop for Death", "Because I could not stop for Death", 1890),
        ("hope_is_the_thing", "希望是长着羽毛的东西", "Hope is the Thing with Feathers", "Hope is the thing with feathers", 1891),
    ],
    "chekhov": [
        ("cherry_orchard", "樱桃园", "The Cherry Orchard", "Вишнёвый сад", 1904),
        ("ward_no6", "第六病室", "Ward No. 6", "Палата № 6", 1892),
    ],
    "wilde": [
        ("dorian_gray", "道林·格雷的画像", "The Picture of Dorian Gray", "The Picture of Dorian Gray", 1890),
        ("importance_earnest", "不可儿戏", "The Importance of Being Earnest", "The Importance of Being Earnest", 1895),
    ],
    "tagore": [
        ("gitanjali", "吉檀迦利", "Gitanjali", "গীতাঞ্জলি", 1910),
        ("stray_birds", "飞鸟集", "Stray Birds", "Stray Birds", 1916),
    ],
    "lu_xun": [
        ("crazy_diary", "狂人日记", "Diary of a Madman", "狂人日記", 1918),
        ("ah_q", "阿Q正传", "The True Story of Ah Q", "阿Q正傳", 1921),
    ],
    "soseki": [
        ("kokoro", "心", "Kokoro", "こころ", 1914),
        ("botchan", "少爷", "Botchan", "坊っちゃん", 1906),
    ],
    "james": [
        ("portrait_lady", "一位女士的画像", "The Portrait of a Lady", "The Portrait of a Lady", 1881),
        ("turn_screw", "螺丝在拧紧", "The Turn of the Screw", "The Turn of the Screw", 1898),
    ],
    "proust": [
        ("recherche", "追忆似水年华", "In Search of Lost Time", "À la recherche du temps perdu", 1913),
        ("swanns_way", "斯万之恋", "Swann's Way", "Du côté de chez Swann", 1913),
    ],
    "joyce": [
        ("ulysses", "尤利西斯", "Ulysses", "Ulysses", 1922),
        ("dubliners", "都柏林人", "Dubliners", "Dubliners", 1914),
    ],
    "kafka": [
        ("metamorphosis", "变形记", "The Metamorphosis", "Die Verwandlung", 1915),
        ("trial", "审判", "The Trial", "Der Prozess", 1925),
    ],
    "woolf": [
        ("mrs_dalloway", "达洛维夫人", "Mrs Dalloway", "Mrs Dalloway", 1925),
        ("to_lighthouse", "到灯塔去", "To the Lighthouse", "To the Lighthouse", 1927),
    ],
    "faulkner": [
        ("sound_fury", "喧哗与骚动", "The Sound and the Fury", "The Sound and the Fury", 1929),
        ("absalom", "押沙龙,押沙龙!", "Absalom, Absalom!", "Absalom, Absalom!", 1936),
    ],
    "hemingway": [
        ("old_man_sea", "老人与海", "The Old Man and the Sea", "The Old Man and the Sea", 1952),
        ("sun_also_rises", "太阳照常升起", "The Sun Also Rises", "The Sun Also Rises", 1926),
    ],
    "borges": [
        ("labyrinths", "小径分岔的花园", "The Garden of Forking Paths", "El jardín de senderos que se bifurcan", 1941),
        ("ficciones", "虚构集", "Ficciones", "Ficciones", 1944),
    ],
    "camus": [
        ("stranger", "局外人", "The Stranger", "L'Étranger", 1942),
        ("plague", "鼠疫", "The Plague", "La Peste", 1947),
    ],
    "orwell": [
        ("nineteen_eighty_four", "一九八四", "Nineteen Eighty-Four", "Nineteen Eighty-Four", 1949),
        ("animal_farm", "动物农场", "Animal Farm", "Animal Farm", 1945),
    ],
    "nabokov": [
        ("lolita", "洛丽塔", "Lolita", "Lolita", 1955),
        ("pnin", "普宁", "Pnin", "Pnin", 1957),
    ],
    "kawabata": [
        ("snow_country", "雪国", "Snow Country", "雪國", 1935),
        ("thousand_cranes", "千只鹤", "Thousand Cranes", "千羽鶴", 1952),
    ],
    "laoshe": [
        ("teahouse", "茶馆", "Teahouse", "茶館", 1957),
        ("camel_xiangzi", "骆驼祥子", "Rickshaw Boy", "駱駝祥子", 1936),
    ],
    "zhangailing": [
        ("qingcheng", "倾城之恋", "Love in a Fallen City", "傾城之戀", 1943),
        ("golden_cangue", "金锁记", "The Golden Cangue", "金鎖記", 1943),
    ],
    "shencongwen": [
        ("biancheng", "边城", "Border Town", "邊城", 1934),
        ("changhe", "长河", "The Long River", "長河", 1943),
    ],
    "rulfo": [
        ("pedro_paramo", "佩德罗·巴拉莫", "Pedro Páramo", "Pedro Páramo", 1955),
        ("burning_plain", "燃烧的平原", "The Burning Plain", "El llano en llamas", 1953),
    ],
    "marquez": [
        ("hundred_years", "百年孤独", "One Hundred Years of Solitude", "Cien años de soledad", 1967),
        ("love_cholera", "霍乱时期的爱情", "Love in the Time of Cholera", "El amor en los tiempos del cólera", 1985),
    ],
    "murakami": [
        ("norwegian_wood", "挪威的森林", "Norwegian Wood", "ノルウェイの森", 1987),
        ("kafka_shore", "海边的卡夫卡", "Kafka on the Shore", "海辺のカフカ", 2002),
    ],
    "yuhua": [
        ("living", "活着", "To Live", "活着", 1993),
        ("xuzhen", "许三观卖血记", "Chronicle of a Blood Merchant", "許三觀賣血記", 1995),
    ],
    "moyan": [
        ("red_sorghum", "红高粱家族", "Red Sorghum", "紅高粱家族", 1986),
        ("frog", "蛙", "Frog", "蛙", 2009),
    ],
    "eliot": [
        ("waste_land", "荒原", "The Waste Land", "The Waste Land", 1922),
        ("four_quartets", "四个四重奏", "Four Quartets", "Four Quartets", 1943),
    ],
    "hessen": [
        ("siddhartha", "悉达多", "Siddhartha", "Siddhartha", 1922),
        ("steppenwolf", "荒原狼", "Steppenwolf", "Der Steppenwolf", 1927),
    ],
    "rimbaud": [
        ("season_in_hell", "地狱一季", "A Season in Hell", "Une saison en enfer", 1873),
        ("illuminations", "彩图集", "Illuminations", "Les Illuminations", 1886),
    ],
    "christie": [
        ("murder_styles", "斯泰尔斯庄园奇案", "The Mysterious Affair at Styles", "The Mysterious Affair at Styles", 1920),
        ("secret_adversary", "暗藏杀机", "The Secret Adversary", "The Secret Adversary", 1922),
        ("murder_links", "高尔夫球场的疑云", "Murder on the Links", "Murder on the Links", 1923),
        ("man_brown_suit", "褐衣男子", "The Man in the Brown Suit", "The Man in the Brown Suit", 1924),
        ("secret_chimneys", "烟囱别墅之谜", "The Secret of Chimneys", "The Secret of Chimneys", 1925),
        ("murder_ackroyd", "罗杰疑案", "The Murder of Roger Ackroyd", "The Murder of Roger Ackroyd", 1926),
        ("big_four", "四大魔头", "The Big Four", "The Big Four", 1927),
        ("blue_train", "蓝色特快上的秘密", "The Mystery of the Blue Train", "The Mystery of the Blue Train", 1928),
        ("seven_dials", "七面钟之谜", "The Seven Dials Mystery", "The Seven Dials Mystery", 1929),
        ("vicarage", "寓所谜案", "The Murder at the Vicarage", "The Murder at the Vicarage", 1930),
        ("sittaford", "斯塔福特疑案", "The Sittaford Mystery", "The Sittaford Mystery", 1931),
        ("peril_end_house", "悬崖山庄奇案", "Peril at End House", "Peril at End House", 1932),
        ("lord_edgware", "人性记录", "Lord Edgware Dies", "Lord Edgware Dies", 1933),
        ("orient_express", "东方快车谋杀案", "Murder on the Orient Express", "Murder on the Orient Express", 1934),
        ("three_act_tragedy", "三幕悲剧", "Three Act Tragedy", "Three Act Tragedy", 1934),
        ("why_evans", "他们为什么不问埃文斯?", "Why Didn't They Ask Evans?", "Why Didn't They Ask Evans?", 1934),
        ("death_clouds", "云中命案", "Death in the Clouds", "Death in the Clouds", 1935),
        ("abc_murders", "ABC谋杀案", "The A.B.C. Murders", "The A.B.C. Murders", 1936),
        ("mesopotamia", "美索不达米亚谋杀案", "Murder in Mesopotamia", "Murder in Mesopotamia", 1936),
        ("cards_table", "底牌", "Cards on the Table", "Cards on the Table", 1936),
        ("dumb_witness", "沉默的证人", "Dumb Witness", "Dumb Witness", 1937),
        ("death_nile", "尼罗河上的惨案", "Death on the Nile", "Death on the Nile", 1937),
        ("appointment_death", "死亡约会", "Appointment with Death", "Appointment with Death", 1938),
        ("poirot_christmas", "圣诞奇案", "Hercule Poirot's Christmas", "Hercule Poirot's Christmas", 1938),
        ("murder_easy", "杀人不难", "Murder Is Easy", "Murder Is Easy", 1939),
        ("and_then_none", "无人生还", "And Then There Were None", "And Then There Were None", 1939),
        ("sad_cypress", "柏棺", "Sad Cypress", "Sad Cypress", 1940),
        ("one_two_buckle", "牙医谋杀案", "One, Two, Buckle My Shoe", "One, Two, Buckle My Shoe", 1940),
        ("evil_sun", "阳光下的罪恶", "Evil Under the Sun", "Evil Under the Sun", 1941),
        ("body_library", "藏书室女尸之谜", "The Body in the Library", "The Body in the Library", 1942),
        ("five_pigs", "五只小猪", "Five Little Pigs", "Five Little Pigs", 1942),
        ("moving_finger", "魔手", "The Moving Finger", "The Moving Finger", 1942),
        ("towards_zero", "零点", "Towards Zero", "Towards Zero", 1944),
        ("death_comes_end", "死亡终局", "Death Comes as the End", "Death Comes as the End", 1944),
        ("sparkling_cyanide", "闪光的氰化物", "Sparkling Cyanide", "Sparkling Cyanide", 1945),
        ("hollow", "空谷幽魂", "The Hollow", "The Hollow", 1946),
        ("taken_flood", "涨潮时节", "Taken at the Flood", "Taken at the Flood", 1948),
        ("crooked_house", "畸形屋", "Crooked House", "Crooked House", 1949),
        ("murder_announced", "谋杀启事", "A Murder Is Announced", "A Murder Is Announced", 1950),
        ("mrs_mcginty", "麦金堤太太之死", "Mrs McGinty's Dead", "Mrs McGinty's Dead", 1952),
        ("after_funeral", "葬礼之后", "After the Funeral", "After the Funeral", 1953),
        ("pocket_rye", "黑麦奇案", "A Pocket Full of Rye", "A Pocket Full of Rye", 1953),
        ("hickory_dock", "国际学舍谋杀案", "Hickory Dickory Dock", "Hickory Dickory Dock", 1955),
        ("dead_mans_folly", "古宅迷踪", "Dead Man's Folly", "Dead Man's Folly", 1956),
        ("paddington", "命案目睹记", "4.50 from Paddington", "4.50 from Paddington", 1957),
        ("ordeal_innocence", "无妄之灾", "Ordeal by Innocence", "Ordeal by Innocence", 1958),
        ("cat_pigeons", "鸽群中的猫", "Cat Among the Pigeons", "Cat Among the Pigeons", 1959),
        ("pale_horse", "白马酒店", "The Pale Horse", "The Pale Horse", 1961),
        ("mirror_crackd", "破镜谋杀案", "The Mirror Crack'd from Side to Side", "The Mirror Crack'd from Side to Side", 1962),
        ("clocks", "钟", "The Clocks", "The Clocks", 1963),
        ("caribbean", "加勒比海之谜", "A Caribbean Mystery", "A Caribbean Mystery", 1964),
        ("bertrams_hotel", "伯特伦旅馆之谜", "At Bertram's Hotel", "At Bertram's Hotel", 1965),
        ("third_girl", "第三个女郎", "Third Girl", "Third Girl", 1966),
        ("endless_night", "长夜", "Endless Night", "Endless Night", 1967),
        ("halloween_party", "万圣节前夜的谋杀案", "Hallowe'en Party", "Hallowe'en Party", 1969),
        ("nemesis", "复仇女神", "Nemesis", "Nemesis", 1971),
        ("elephants", "大象的证词", "Elephants Can Remember", "Elephants Can Remember", 1972),
        ("curtain", "帷幕", "Curtain", "Curtain", 1975),
        ("sleeping_murder", "沉睡谋杀案", "Sleeping Murder", "Sleeping Murder", 1976),
    ],
}

# (source_work_id, target_work_id, evidence, note)
# 语义:(source) 这本书在正文中提及了 (target) 这本书。
# evidence = 摘抄文本,即正文某片段出现另一本书的名称(演示数据)。
EDGES: list[tuple] = [
    ("iliad", "aeneid", "演示摘抄：维吉尔在史诗开篇呼应荷马的战争母题", "正文片段提及"),
    ("iliad", "war_peace", "演示摘抄：托尔斯泰反复阅读荷马史诗", "正文转述该书内容"),
    ("aeneid", "divine_comedy", "演示摘抄：但丁以维吉尔为地狱之旅的引路人", "人物对话中提及"),
    ("divine_comedy", "faust", "演示摘抄：浮士德的结构与神曲的朝圣之旅遥相呼应", "序言或注释中引用"),
    ("divine_comedy", "waste_land", "演示摘抄：荒原中对神曲地狱篇的化用", "正文片段提及"),
    ("faust", "steppenwolf", "演示摘抄：荒原狼中反复引用浮士德与歌德", "人物对话中提及"),
    ("steppenwolf", "norwegian_wood", "演示摘抄：村上春树借主人公之口谈论荒原狼", "正文转述该书内容"),
    ("hamlet", "faust", "演示摘抄：浮士德独白与哈姆雷特的生死之问", "序言或注释中引用"),
    ("king_lear", "sound_fury", "演示摘抄：福克纳笔下家族疯癫与李尔王呼应", "正文片段提及"),
    ("raven", "fleurs_du_mal", "演示摘抄：波德莱尔翻译并评介爱伦·坡", "序言或注释中引用"),
    ("fleurs_du_mal", "season_in_hell", "演示摘抄：兰波的诗学宣言回应恶之花", "正文转述该书内容"),
    ("fleurs_du_mal", "waste_land", "演示摘抄：荒原的意象与恶之花相通", "正文片段提及"),
    ("overcoat", "notes_underground", "演示摘抄：我们都来自果戈里的外套", "人物对话中提及"),
    ("overcoat", "metamorphosis", "演示摘抄：小人物异化为虫的荒诞承续", "正文片段提及"),
    ("notes_underground", "stranger", "演示摘抄：局外人的疏离感可溯至地下室手记", "正文转述该书内容"),
    ("notes_underground", "crazy_diary", "演示摘抄：狂人日记的独白体与地下室手记相近", "序言或注释中引用"),
    ("diary_madman", "crazy_diary", "演示摘抄：鲁迅狂人日记与果戈里同名作品形成回声", "正文片段提及"),
    ("crime_punishment", "stranger", "演示摘抄：加缪对罪与罚的伦理追问的回应", "正文转述该书内容"),
    ("crime_punishment", "trial", "演示摘抄：卡夫卡笔下罪与罚的审判母题", "人物对话中提及"),
    ("madame_bovary", "anna_karenina", "演示摘抄：托尔斯泰借鉴福楼拜的客观叙述", "序言或注释中引用"),
    ("madame_bovary", "ulysses", "演示摘抄：乔伊斯推崇包法利夫人的精确文体", "正文片段提及"),
    ("don_quixote", "david_copperfield", "演示摘抄：狄更斯对堂吉诃德式人物的喜爱", "人物对话中提及"),
    ("don_quixote", "old_man_sea", "演示摘抄：老人与海的硬汉精神与堂吉诃德呼应", "正文转述该书内容"),
    ("don_quixote", "hundred_years", "演示摘抄：百年孤独的戏谑与反讽有堂吉诃德影子", "序言或注释中引用"),
    ("lisao", "jiang_jin_jiu", "演示摘抄：李白的浪漫想象承接屈骚传统", "正文片段提及"),
    ("jiu_ge", "qiuxing_bashou", "演示摘抄：杜甫诗中的楚辞意象", "正文转述该书内容"),
    ("genji", "snow_country", "演示摘抄：川端康成的物哀美学承自源氏物语", "人物对话中提及"),
    ("hongloumeng", "qingcheng", "演示摘抄：张爱玲受红楼梦世情笔法影响", "序言或注释中引用"),
    ("hongloumeng", "golden_cangue", "演示摘抄：金锁记的家庭书写与红楼梦的对照", "正文片段提及"),
    ("gitanjali", "siddhartha", "演示摘抄：黑塞的东方哲思与泰戈尔呼应", "正文转述该书内容"),
    ("doll_house", "cherry_orchard", "演示摘抄：契诃夫戏剧延续易卜生的社会问题剧", "人物对话中提及"),
    ("ward_no6", "ah_q", "演示摘抄：鲁迅推崇并翻译契诃夫的作品", "序言或注释中引用"),
    ("dubliners", "mrs_dalloway", "演示摘抄：伍尔夫对乔伊斯顿悟式叙事的回应", "正文片段提及"),
    ("ulysses", "sound_fury", "演示摘抄：福克纳的意识流深受尤利西斯启发", "正文转述该书内容"),
    ("recherche", "mrs_dalloway", "演示摘抄：伍尔夫阅读普鲁斯特后转向内心时间", "人物对话中提及"),
    ("recherche", "sound_fury", "演示摘抄：福克纳对时间记忆的处理与普鲁斯特相近", "正文片段提及"),
    ("sound_fury", "hundred_years", "演示摘抄：马尔克斯反复阅读喧哗与骚动", "序言或注释中引用"),
    ("pedro_paramo", "hundred_years", "演示摘抄：百年孤独开篇与佩德罗·巴拉莫的对话", "正文片段提及"),
    ("labyrinths", "hundred_years", "演示摘抄：马尔克斯与博尔赫斯的时间迷宫", "正文转述该书内容"),
    ("ficciones", "kafka_shore", "演示摘抄：海边的卡夫卡承袭博尔赫斯的迷宫叙事", "人物对话中提及"),
    ("metamorphosis", "stranger", "演示摘抄：加缪对卡夫卡荒诞的继承与转化", "序言或注释中引用"),
    ("trial", "kafka_shore", "演示摘抄：海边的卡夫卡与审判的预言结构", "正文片段提及"),
    ("old_man_sea", "living", "演示摘抄：余华推崇海明威的简洁文体", "正文转述该书内容"),
    ("war_peace", "living", "演示摘抄：余华对托尔斯泰的宏大叙事的致敬", "人物对话中提及"),
    ("hundred_years", "red_sorghum", "演示摘抄：莫言受拉美魔幻现实主义影响", "序言或注释中引用"),
    ("portrait_lady", "mrs_dalloway", "演示摘抄：伍尔夫对亨利·詹姆斯心理小说的承续", "正文片段提及"),
    ("cherry_orchard", "teahouse", "演示摘抄：茶馆的群像结构与契诃夫戏剧相通", "正文转述该书内容"),
    ("ah_q", "teahouse", "演示摘抄：老舍对中国国民性的讽刺接续鲁迅", "人物对话中提及"),
    ("ward_no6", "crazy_diary", "演示摘抄：鲁迅对第六病室式绝望的呼应", "正文片段提及"),
    ("odyssey", "ulysses", "演示摘抄：尤利西斯以奥德赛为原型框架", "序言或注释中引用"),
    ("rue_morgue", "orient_express", "演示摘抄：波洛系列常被追溯至爱伦·坡开创的侦探小说传统", "序言或注释中引用"),
    ("murder_styles", "orient_express", "演示摘抄：东方快车谋杀案中波洛回顾斯泰尔斯庄园的首案", "人物对话中提及"),
    ("orient_express", "death_nile", "演示摘抄：尼罗河上的惨案延续波洛系列案件脉络", "正文转述该书内容"),
    ("murder_ackroyd", "and_then_none", "演示摘抄：无人生还的叙事实验被视为罗杰疑案式创新的回响", "正文片段提及"),
    ("and_then_none", "curtain", "演示摘抄：帷幕作为波洛谢幕之作与无人生还遥相呼应", "序言或注释中引用"),
]


def build() -> dict:
    assert len(AUTHORS) == 51, f"expected 51 authors, got {len(AUTHORS)}"
    assert len(WORKS) == 51, f"expected 51 author keys, got {len(WORKS)}"

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    authors: list[dict] = []
    works: list[dict] = []

    for author_id, (original_name, name_cn, name_en, birth, death, nationality, language) in AUTHORS.items():
        authors.append(
            {
                "id": author_id,
                "nationality": nationality,
                "originalName": original_name,
                "Name_CN": name_cn,
                "Name_EN": name_en,
                "birthYear": birth,
                "deathYear": death,
                "primaryLanguage": language,
                "bio": f"演示简介：{name_cn}（{name_en}），{nationality}作家，主要写作语言 {language}。",
                "createdAt": now,
                "updatedAt": now,
            }
        )
        for work_id, title_cn, title_en, original_title, year in WORKS[author_id]:
            works.append(
                {
                    "id": work_id,
                    "language": language,
                    "originalTitle": original_title,
                    "Title_CN": title_cn,
                    "Title_EN": title_en,
                    "publicationYear": year if year >= 1700 else None,
                    "creationYear": year if year < 1700 else None,
                    "summary": f"演示简介：{title_cn}（{original_title}）为{name_cn}所作，{year}年{'出版' if year >= 1700 else '创作'}。",
                    "createdAt": now,
                    "updatedAt": now,
                    "author_id": author_id,
                }
            )

    work_ids = {w["id"] for w in works}
    edges: list[dict] = []
    for source, target, evidence, note in EDGES:
        assert source in work_ids, f"unknown source work: {source}"
        assert target in work_ids, f"unknown target work: {target}"
        edges.append(
            {
                "source": source,
                "target": target,
                "evidence": evidence,
                "note": "演示备注：" + note,
            }
        )

    assert len(works) == 159, f"expected 159 works, got {len(works)}"
    assert len(edges) == 55, f"expected 55 edges, got {len(edges)}"

    return {
        "meta": {
            "name": "echo-graph demo seed",
            "demo": True,
            "note": "SYNTHETIC DEMO DATA - fabricated ECHO edges and evidence, not scholarly fact.",
        },
        "authors": authors,
        "works": works,
        "edges": edges,
    }


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    payload = build()
    out = DATA_DIR / "seed.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}  (authors={len(payload['authors'])}, works={len(payload['works'])}, edges={len(payload['edges'])})")


if __name__ == "__main__":
    main()
