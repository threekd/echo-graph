"""Generate demo seed data for Echo Graph.

Output: data/seed.json

IMPORTANT: All data in this file is SYNTHETIC DEMO DATA. Author/work metadata
roughly follows real literary history, but every influence edge and its quoted
evidence is fabricated for demonstration purposes and must NOT be treated as
scholarly fact. Real curation should replace this before any public release.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# id -> (name_zh, name_en, birth, death, nationality, language, era)
AUTHORS: dict[str, tuple] = {
    "homer": ("荷马", "Homer", -800, -700, "古希腊", "古希腊语", "古希腊"),
    "virgil": ("维吉尔", "Virgil", -70, -19, "古罗马", "拉丁语", "古罗马"),
    "dante": ("但丁", "Dante", 1265, 1321, "意大利", "意大利语", "中世纪"),
    "chaucer": ("乔叟", "Chaucer", 1343, 1400, "英国", "中古英语", "中世纪"),
    "quyuan": ("屈原", "Qu Yuan", -340, -278, "中国", "古汉语", "战国"),
    "dufu": ("杜甫", "Du Fu", 712, 770, "中国", "古汉语", "唐代"),
    "libai": ("李白", "Li Bai", 701, 762, "中国", "古汉语", "唐代"),
    "shakespeare": ("莎士比亚", "Shakespeare", 1564, 1616, "英国", "英语", "文艺复兴"),
    "cervantes": ("塞万提斯", "Cervantes", 1547, 1616, "西班牙", "西班牙语", "文艺复兴"),
    "shikibu": ("紫式部", "Murasaki Shikibu", 973, 1014, "日本", "古典日语", "平安时代"),
    "caoxueqin": ("曹雪芹", "Cao Xueqin", 1715, 1763, "中国", "古汉语", "清代"),
    "goethe": ("歌德", "Goethe", 1749, 1832, "德国", "德语", "启蒙与古典"),
    "balzac": ("巴尔扎克", "Balzac", 1799, 1850, "法国", "法语", "19世纪"),
    "poe": ("爱伦·坡", "Edgar Allan Poe", 1809, 1849, "美国", "英语", "19世纪"),
    "gogol": ("果戈里", "Gogol", 1809, 1852, "俄国", "俄语", "19世纪"),
    "dickens": ("狄更斯", "Dickens", 1812, 1870, "英国", "英语", "19世纪"),
    "dostoevsky": ("陀思妥耶夫斯基", "Dostoevsky", 1821, 1881, "俄国", "俄语", "19世纪"),
    "flaubert": ("福楼拜", "Flaubert", 1821, 1880, "法国", "法语", "19世纪"),
    "baudelaire": ("波德莱尔", "Baudelaire", 1821, 1867, "法国", "法语", "19世纪"),
    "tolstoy": ("托尔斯泰", "Tolstoy", 1828, 1910, "俄国", "俄语", "19世纪"),
    "ibsen": ("易卜生", "Ibsen", 1828, 1906, "挪威", "挪威语", "19世纪"),
    "dickinson": ("狄金森", "Dickinson", 1830, 1886, "美国", "英语", "19世纪"),
    "chekhov": ("契诃夫", "Chekhov", 1860, 1904, "俄国", "俄语", "19世纪末"),
    "wilde": ("王尔德", "Wilde", 1854, 1900, "爱尔兰", "英语", "19世纪末"),
    "tagore": ("泰戈尔", "Tagore", 1861, 1941, "印度", "孟加拉语", "20世纪初"),
    "lu_xun": ("鲁迅", "Lu Xun", 1881, 1936, "中国", "中文", "中国现代"),
    "soseki": ("夏目漱石", "Natsume Soseki", 1867, 1916, "日本", "日语", "日本近代"),
    "james": ("亨利·詹姆斯", "Henry James", 1843, 1916, "美国", "英语", "19-20世纪"),
    "proust": ("普鲁斯特", "Proust", 1871, 1922, "法国", "法语", "20世纪初"),
    "joyce": ("乔伊斯", "Joyce", 1882, 1941, "爱尔兰", "英语", "20世纪初"),
    "kafka": ("卡夫卡", "Kafka", 1883, 1924, "奥地利", "德语", "20世纪初"),
    "woolf": ("伍尔夫", "Woolf", 1882, 1941, "英国", "英语", "20世纪初"),
    "faulkner": ("福克纳", "Faulkner", 1897, 1962, "美国", "英语", "20世纪"),
    "hemingway": ("海明威", "Hemingway", 1899, 1961, "美国", "英语", "20世纪"),
    "borges": ("博尔赫斯", "Borges", 1899, 1986, "阿根廷", "西班牙语", "20世纪"),
    "camus": ("加缪", "Camus", 1913, 1960, "法国", "法语", "20世纪"),
    "orwell": ("奥威尔", "Orwell", 1903, 1950, "英国", "英语", "20世纪"),
    "nabokov": ("纳博科夫", "Nabokov", 1899, 1977, "俄裔美籍", "英语", "20世纪"),
    "kawabata": ("川端康成", "Kawabata", 1899, 1972, "日本", "日语", "20世纪"),
    "laoshe": ("老舍", "Lao She", 1899, 1966, "中国", "中文", "中国现代"),
    "zhangailing": ("张爱玲", "Eileen Chang", 1920, 1995, "中国", "中文", "中国现代"),
    "shencongwen": ("沈从文", "Shen Congwen", 1902, 1988, "中国", "中文", "中国现代"),
    "rulfo": ("鲁尔福", "Rulfo", 1917, 1986, "墨西哥", "西班牙语", "20世纪"),
    "marquez": ("马尔克斯", "Márquez", 1927, 2014, "哥伦比亚", "西班牙语", "20世纪"),
    "murakami": ("村上春树", "Murakami", 1949, None, "日本", "日语", "当代"),
    "yuhua": ("余华", "Yu Hua", 1960, None, "中国", "中文", "当代"),
    "moyan": ("莫言", "Mo Yan", 1955, None, "中国", "中文", "当代"),
    "eliot": ("艾略特", "T. S. Eliot", 1888, 1965, "英裔美籍", "英语", "20世纪"),
    "hessen": ("黑塞", "Hesse", 1877, 1962, "德裔瑞士", "德语", "20世纪"),
    "rimbaud": ("兰波", "Rimbaud", 1854, 1891, "法国", "法语", "19世纪"),
}

# author_id -> list of (work_id, title_zh, title_en, year, language, genre)
WORKS: dict[str, list[tuple]] = {
    "homer": [
        ("iliad", "伊利亚特", "Iliad", -750, "古希腊语", "史诗"),
        ("odyssey", "奥德赛", "Odyssey", -700, "古希腊语", "史诗"),
    ],
    "virgil": [
        ("aeneid", "埃涅阿斯纪", "Aeneid", -19, "拉丁语", "史诗"),
        ("georgics", "农事诗", "Georgics", -29, "拉丁语", "长诗"),
    ],
    "dante": [
        ("divine_comedy", "神曲", "The Divine Comedy", 1320, "意大利语", "长诗"),
        ("vita_nuova", "新生", "La Vita Nuova", 1295, "意大利语", "诗集"),
    ],
    "chaucer": [
        ("canterbury_tales", "坎特伯雷故事集", "The Canterbury Tales", 1400, "中古英语", "叙事诗"),
        ("troilus", "特洛伊罗斯与克瑞西达", "Troilus and Criseyde", 1385, "中古英语", "叙事诗"),
    ],
    "quyuan": [
        ("lisao", "离骚", "Li Sao", -300, "古汉语", "楚辞"),
        ("jiu_ge", "九歌", "Nine Songs", -300, "古汉语", "楚辞"),
    ],
    "dufu": [
        ("sanli_sanbie", "三吏三别", "Three Officials and Three Partings", 759, "古汉语", "诗"),
        ("qiuxing_bashou", "秋兴八首", "Eight Autumn Meditations", 766, "古汉语", "诗"),
    ],
    "libai": [
        ("jiang_jin_jiu", "将进酒", "Invitation to Wine", 752, "古汉语", "诗"),
        ("jing_ye_si", "静夜思", "Quiet Night Thought", 726, "古汉语", "诗"),
    ],
    "shakespeare": [
        ("hamlet", "哈姆雷特", "Hamlet", 1603, "英语", "戏剧"),
        ("king_lear", "李尔王", "King Lear", 1606, "英语", "戏剧"),
        ("macbeth", "麦克白", "Macbeth", 1606, "英语", "戏剧"),
    ],
    "cervantes": [
        ("don_quixote", "堂吉诃德", "Don Quixote", 1615, "西班牙语", "小说"),
        ("exemplary_novels", "惩恶扬善故事集", "Novelas ejemplares", 1613, "西班牙语", "短篇集"),
    ],
    "shikibu": [
        ("genji", "源氏物语", "The Tale of Genji", 1010, "古典日语", "物语"),
        ("shikibu_diary", "紫式部日记", "The Diary of Lady Murasaki", 1010, "古典日语", "日记"),
    ],
    "caoxueqin": [
        ("hongloumeng", "红楼梦", "Dream of the Red Chamber", 1791, "古汉语", "小说"),
    ],
    "goethe": [
        ("faust", "浮士德", "Faust", 1831, "德语", "诗剧"),
        ("werther", "少年维特的烦恼", "The Sorrows of Young Werther", 1774, "德语", "书信体小说"),
    ],
    "balzac": [
        ("pere_goriot", "高老头", "Old Goriot", 1835, "法语", "小说"),
        ("comedie_humaine", "人间喜剧", "La Comédie Humaine", 1850, "法语", "小说系列"),
    ],
    "poe": [
        ("raven", "乌鸦", "The Raven", 1845, "英语", "诗"),
        ("rue_morgue", "莫格街凶杀案", "The Murders in the Rue Morgue", 1841, "英语", "小说"),
    ],
    "gogol": [
        ("overcoat", "外套", "The Overcoat", 1842, "俄语", "小说"),
        ("diary_madman", "狂人日记", "Diary of a Madman", 1835, "俄语", "小说"),
    ],
    "dickens": [
        ("oliver_twist", "雾都孤儿", "Oliver Twist", 1838, "英语", "小说"),
        ("david_copperfield", "大卫·科波菲尔", "David Copperfield", 1850, "英语", "小说"),
    ],
    "dostoevsky": [
        ("notes_underground", "地下室手记", "Notes from Underground", 1864, "俄语", "小说"),
        ("crime_punishment", "罪与罚", "Crime and Punishment", 1866, "俄语", "小说"),
    ],
    "flaubert": [
        ("madame_bovary", "包法利夫人", "Madame Bovary", 1857, "法语", "小说"),
        ("education_sentimentale", "情感教育", "Sentimental Education", 1869, "法语", "小说"),
    ],
    "baudelaire": [
        ("fleurs_du_mal", "恶之花", "Les Fleurs du Mal", 1857, "法语", "诗集"),
        ("paris_spleen", "巴黎的忧郁", "Le Spleen de Paris", 1869, "法语", "散文诗"),
    ],
    "tolstoy": [
        ("war_peace", "战争与和平", "War and Peace", 1869, "俄语", "小说"),
        ("anna_karenina", "安娜·卡列尼娜", "Anna Karenina", 1877, "俄语", "小说"),
    ],
    "ibsen": [
        ("doll_house", "玩偶之家", "A Doll's House", 1879, "挪威语", "戏剧"),
        ("ghosts", "群鬼", "Ghosts", 1881, "挪威语", "戏剧"),
    ],
    "dickinson": [
        ("because_i_could_not_stop", "因为我不能停步等待死神", "Because I Could Not Stop for Death", 1890, "英语", "诗"),
        ("hope_is_the_thing", "希望是长着羽毛的东西", "Hope is the Thing with Feathers", 1891, "英语", "诗"),
    ],
    "chekhov": [
        ("cherry_orchard", "樱桃园", "The Cherry Orchard", 1904, "俄语", "戏剧"),
        ("ward_no6", "第六病室", "Ward No. 6", 1892, "俄语", "小说"),
    ],
    "wilde": [
        ("dorian_gray", "道林·格雷的画像", "The Picture of Dorian Gray", 1890, "英语", "小说"),
        ("importance_earnest", "不可儿戏", "The Importance of Being Earnest", 1895, "英语", "戏剧"),
    ],
    "tagore": [
        ("gitanjali", "吉檀迦利", "Gitanjali", 1910, "孟加拉语", "诗集"),
        ("stray_birds", "飞鸟集", "Stray Birds", 1916, "孟加拉语", "诗集"),
    ],
    "lu_xun": [
        ("crazy_diary", "狂人日记", "Diary of a Madman", 1918, "中文", "小说"),
        ("ah_q", "阿Q正传", "The True Story of Ah Q", 1921, "中文", "小说"),
    ],
    "soseki": [
        ("kokoro", "心", "Kokoro", 1914, "日语", "小说"),
        ("botchan", "少爷", "Botchan", 1906, "日语", "小说"),
    ],
    "james": [
        ("portrait_lady", "一位女士的画像", "The Portrait of a Lady", 1881, "英语", "小说"),
        ("turn_screw", "螺丝在拧紧", "The Turn of the Screw", 1898, "英语", "小说"),
    ],
    "proust": [
        ("recherche", "追忆似水年华", "In Search of Lost Time", 1913, "法语", "小说"),
        ("swanns_way", "斯万之恋", "Swann's Way", 1913, "法语", "小说"),
    ],
    "joyce": [
        ("ulysses", "尤利西斯", "Ulysses", 1922, "英语", "小说"),
        ("dubliners", "都柏林人", "Dubliners", 1914, "英语", "短篇集"),
    ],
    "kafka": [
        ("metamorphosis", "变形记", "The Metamorphosis", 1915, "德语", "小说"),
        ("trial", "审判", "The Trial", 1925, "德语", "小说"),
    ],
    "woolf": [
        ("mrs_dalloway", "达洛维夫人", "Mrs Dalloway", 1925, "英语", "小说"),
        ("to_lighthouse", "到灯塔去", "To the Lighthouse", 1927, "英语", "小说"),
    ],
    "faulkner": [
        ("sound_fury", "喧哗与骚动", "The Sound and the Fury", 1929, "英语", "小说"),
        ("absalom", "押沙龙,押沙龙!", "Absalom, Absalom!", 1936, "英语", "小说"),
    ],
    "hemingway": [
        ("old_man_sea", "老人与海", "The Old Man and the Sea", 1952, "英语", "小说"),
        ("sun_also_rises", "太阳照常升起", "The Sun Also Rises", 1926, "英语", "小说"),
    ],
    "borges": [
        ("labyrinths", "小径分岔的花园", "The Garden of Forking Paths", 1941, "西班牙语", "短篇"),
        ("ficciones", "虚构集", "Ficciones", 1944, "西班牙语", "短篇集"),
    ],
    "camus": [
        ("stranger", "局外人", "The Stranger", 1942, "法语", "小说"),
        ("plague", "鼠疫", "The Plague", 1947, "法语", "小说"),
    ],
    "orwell": [
        ("nineteen_eighty_four", "一九八四", "Nineteen Eighty-Four", 1949, "英语", "小说"),
        ("animal_farm", "动物农场", "Animal Farm", 1945, "英语", "小说"),
    ],
    "nabokov": [
        ("lolita", "洛丽塔", "Lolita", 1955, "英语", "小说"),
        ("pnin", "普宁", "Pnin", 1957, "英语", "小说"),
    ],
    "kawabata": [
        ("snow_country", "雪国", "Snow Country", 1935, "日语", "小说"),
        ("thousand_cranes", "千只鹤", "Thousand Cranes", 1952, "日语", "小说"),
    ],
    "laoshe": [
        ("teahouse", "茶馆", "Teahouse", 1957, "中文", "戏剧"),
        ("camel_xiangzi", "骆驼祥子", "Rickshaw Boy", 1936, "中文", "小说"),
    ],
    "zhangailing": [
        ("qingcheng", "倾城之恋", "Love in a Fallen City", 1943, "中文", "小说"),
        ("golden_cangue", "金锁记", "The Golden Cangue", 1943, "中文", "小说"),
    ],
    "shencongwen": [
        ("biancheng", "边城", "Border Town", 1934, "中文", "小说"),
        ("changhe", "长河", "The Long River", 1943, "中文", "小说"),
    ],
    "rulfo": [
        ("pedro_paramo", "佩德罗·巴拉莫", "Pedro Páramo", 1955, "西班牙语", "小说"),
        ("burning_plain", "燃烧的平原", "The Burning Plain", 1953, "西班牙语", "短篇集"),
    ],
    "marquez": [
        ("hundred_years", "百年孤独", "One Hundred Years of Solitude", 1967, "西班牙语", "小说"),
        ("love_cholera", "霍乱时期的爱情", "Love in the Time of Cholera", 1985, "西班牙语", "小说"),
    ],
    "murakami": [
        ("norwegian_wood", "挪威的森林", "Norwegian Wood", 1987, "日语", "小说"),
        ("kafka_shore", "海边的卡夫卡", "Kafka on the Shore", 2002, "日语", "小说"),
    ],
    "yuhua": [
        ("living", "活着", "To Live", 1993, "中文", "小说"),
        ("xuzhen", "许三观卖血记", "Chronicle of a Blood Merchant", 1995, "中文", "小说"),
    ],
    "moyan": [
        ("red_sorghum", "红高粱家族", "Red Sorghum", 1986, "中文", "小说"),
        ("frog", "蛙", "Frog", 2009, "中文", "小说"),
    ],
    "eliot": [
        ("waste_land", "荒原", "The Waste Land", 1922, "英语", "长诗"),
        ("four_quartets", "四个四重奏", "Four Quartets", 1943, "英语", "长诗"),
    ],
    "hessen": [
        ("siddhartha", "悉达多", "Siddhartha", 1922, "德语", "小说"),
        ("steppenwolf", "荒原狼", "Steppenwolf", 1927, "德语", "小说"),
    ],
    "rimbaud": [
        ("season_in_hell", "地狱一季", "A Season in Hell", 1873, "法语", "诗集"),
        ("illuminations", "彩图集", "Illuminations", 1886, "法语", "散文诗"),
    ],
}

# (source_work_id, target_work_id, kind, confidence, quote)
# kind: homage 致敬 | quote 引用 | rebuttal 回应 | translation 翻译传播 | mentorship 师承
EDGES: list[tuple] = [
    ("iliad", "aeneid", "homage", 0.90, "演示引文：维吉尔在史诗开篇呼应荷马的战争母题"),
    ("iliad", "war_peace", "homage", 0.85, "演示引文：托尔斯泰反复阅读荷马史诗"),
    ("aeneid", "divine_comedy", "mentorship", 0.92, "演示引文：但丁以维吉尔为地狱之旅的引路人"),
    ("divine_comedy", "faust", "homage", 0.82, "演示引文：浮士德的结构与神曲的朝圣之旅遥相呼应"),
    ("divine_comedy", "waste_land", "homage", 0.78, "演示引文：荒原中对神曲地狱篇的化用"),
    ("faust", "steppenwolf", "homage", 0.80, "演示引文：荒原狼中反复引用浮士德与歌德"),
    ("steppenwolf", "norwegian_wood", "homage", 0.72, "演示引文：村上春树借主人公之口谈论荒原狼"),
    ("hamlet", "faust", "quote", 0.75, "演示引文：浮士德独白与哈姆雷特的生死之问"),
    ("king_lear", "sound_fury", "homage", 0.70, "演示引文：福克纳笔下家族疯癫与李尔王呼应"),
    ("raven", "fleurs_du_mal", "translation", 0.90, "演示引文：波德莱尔翻译并评介爱伦·坡"),
    ("fleurs_du_mal", "season_in_hell", "mentorship", 0.84, "演示引文：兰波的诗学宣言回应恶之花"),
    ("fleurs_du_mal", "waste_land", "homage", 0.76, "演示引文：荒原的意象与恶之花相通"),
    ("overcoat", "notes_underground", "mentorship", 0.88, "演示引文：我们都来自果戈里的外套"),
    ("overcoat", "metamorphosis", "homage", 0.74, "演示引文：小人物异化为虫的荒诞承续"),
    ("notes_underground", "stranger", "homage", 0.86, "演示引文：局外人的疏离感可溯至地下室手记"),
    ("notes_underground", "crazy_diary", "homage", 0.80, "演示引文：狂人日记的独白体与地下室手记相近"),
    ("diary_madman", "crazy_diary", "homage", 0.85, "演示引文：鲁迅狂人日记与果戈里同名作品形成回声"),
    ("crime_punishment", "stranger", "homage", 0.75, "演示引文：加缪对罪与罚的伦理追问的回应"),
    ("crime_punishment", "trial", "homage", 0.78, "演示引文：卡夫卡笔下罪与罚的审判母题"),
    ("madame_bovary", "anna_karenina", "mentorship", 0.80, "演示引文：托尔斯泰借鉴福楼拜的客观叙述"),
    ("madame_bovary", "ulysses", "mentorship", 0.77, "演示引文：乔伊斯推崇包法利夫人的精确文体"),
    ("don_quixote", "david_copperfield", "homage", 0.73, "演示引文：狄更斯对堂吉诃德式人物的喜爱"),
    ("don_quixote", "old_man_sea", "homage", 0.74, "演示引文：老人与海的硬汉精神与堂吉诃德呼应"),
    ("don_quixote", "hundred_years", "homage", 0.76, "演示引文：百年孤独的戏谑与反讽有堂吉诃德影子"),
    ("lisao", "jiang_jin_jiu", "homage", 0.82, "演示引文：李白的浪漫想象承接屈骚传统"),
    ("jiu_ge", "qiuxing_bashou", "homage", 0.70, "演示引文：杜甫诗中的楚辞意象"),
    ("genji", "snow_country", "homage", 0.75, "演示引文：川端康成的物哀美学承自源氏物语"),
    ("hongloumeng", "qingcheng", "homage", 0.78, "演示引文：张爱玲受红楼梦世情笔法影响"),
    ("hongloumeng", "golden_cangue", "homage", 0.72, "演示引文：金锁记的家庭书写与红楼梦的对照"),
    ("gitanjali", "siddhartha", "homage", 0.70, "演示引文：黑塞的东方哲思与泰戈尔呼应"),
    ("doll_house", "cherry_orchard", "mentorship", 0.71, "演示引文：契诃夫戏剧延续易卜生的社会问题剧"),
    ("ward_no6", "ah_q", "homage", 0.79, "演示引文：鲁迅推崇并翻译契诃夫的作品"),
    ("dubliners", "mrs_dalloway", "homage", 0.82, "演示引文：伍尔夫对乔伊斯顿悟式叙事的回应"),
    ("ulysses", "sound_fury", "mentorship", 0.83, "演示引文：福克纳的意识流深受尤利西斯启发"),
    ("recherche", "mrs_dalloway", "mentorship", 0.74, "演示引文：伍尔夫阅读普鲁斯特后转向内心时间"),
    ("recherche", "sound_fury", "homage", 0.72, "演示引文：福克纳对时间记忆的处理与普鲁斯特相近"),
    ("sound_fury", "hundred_years", "homage", 0.84, "演示引文：马尔克斯反复阅读喧哗与骚动"),
    ("pedro_paramo", "hundred_years", "mentorship", 0.87, "演示引文：百年孤独开篇与佩德罗·巴拉莫的对话"),
    ("labyrinths", "hundred_years", "homage", 0.72, "演示引文：马尔克斯与博尔赫斯的时间迷宫"),
    ("ficciones", "kafka_shore", "homage", 0.78, "演示引文：海边的卡夫卡承袭博尔赫斯的迷宫叙事"),
    ("metamorphosis", "stranger", "homage", 0.76, "演示引文：加缪对卡夫卡荒诞的继承与转化"),
    ("trial", "kafka_shore", "homage", 0.80, "演示引文：海边的卡夫卡与审判的预言结构"),
    ("old_man_sea", "living", "mentorship", 0.73, "演示引文：余华推崇海明威的简洁文体"),
    ("war_peace", "living", "mentorship", 0.75, "演示引文：余华对托尔斯泰的宏大叙事的致敬"),
    ("hundred_years", "red_sorghum", "homage", 0.80, "演示引文：莫言受拉美魔幻现实主义影响"),
    ("portrait_lady", "mrs_dalloway", "mentorship", 0.71, "演示引文：伍尔夫对亨利·詹姆斯心理小说的承续"),
    ("cherry_orchard", "teahouse", "homage", 0.74, "演示引文：茶馆的群像结构与契诃夫戏剧相通"),
    ("ah_q", "teahouse", "homage", 0.68, "演示引文：老舍对中国国民性的讽刺接续鲁迅"),
    ("ward_no6", "crazy_diary", "homage", 0.72, "演示引文：鲁迅对第六病室式绝望的呼应"),
    ("odyssey", "ulysses", "homage", 0.88, "演示引文：尤利西斯以奥德赛为原型框架"),
]


def build() -> dict:
    assert len(AUTHORS) == 50, f"expected 50 authors, got {len(AUTHORS)}"
    assert len(WORKS) == 50, f"expected 50 author keys, got {len(WORKS)}"

    authors: list[dict] = []
    works: list[dict] = []
    for author_id, (name, name_en, birth, death, nationality, language, era) in AUTHORS.items():
        authors.append(
            {
                "id": author_id,
                "name": name,
                "name_en": name_en,
                "birth": birth,
                "death": death,
                "nationality": nationality,
                "language": language,
                "era": era,
            }
        )
        for work_id, title, title_en, year, lang, genre in WORKS[author_id]:
            works.append(
                {
                    "id": work_id,
                    "title": title,
                    "title_en": title_en,
                    "year": year,
                    "language": lang,
                    "genre": genre,
                    "author_id": author_id,
                }
            )

    work_ids = {w["id"] for w in works}
    edges: list[dict] = []
    for source, target, kind, confidence, quote in EDGES:
        assert source in work_ids, f"unknown source work: {source}"
        assert target in work_ids, f"unknown target work: {target}"
        edges.append(
            {
                "source": source,
                "target": target,
                "kind": kind,
                "confidence": confidence,
                "quote": quote,
            }
        )

    assert len(works) == 100, f"expected 100 works, got {len(works)}"
    assert len(edges) == 50, f"expected 50 edges, got {len(edges)}"

    return {
        "meta": {
            "name": "echo-graph demo seed",
            "demo": True,
            "note": "SYNTHETIC DEMO DATA - fabricated influence edges and quotes, not scholarly fact.",
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
