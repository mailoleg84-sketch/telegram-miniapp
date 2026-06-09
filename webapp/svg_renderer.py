"""SVG-рендер карточек слов (вынесено из webapp/server.py).

Чистые функции построения SVG: иконки тем, фон/цвет/иконка по слову,
учебная сцена по visual_type. Без HTTP/БД/состояния — только stdlib.
"""
import hashlib


TOPIC_IMAGE_STYLES = {
    "animals": ("#eaf7ff", "#2f9df4", "paw"),
    "art": ("#fff0f6", "#ff5c8a", "music"),
    "body": ("#fff3e6", "#ff7a45", "heart"),
    "clothes": ("#f2efff", "#7c5cff", "shirt"),
    "communication": ("#eef8ff", "#2481cc", "bubble"),
    "culture": ("#f4f0ff", "#7c5cff", "book"),
    "everyday": ("#eefaf8", "#2ec4b6", "home"),
    "exams": ("#eef8ff", "#2481cc", "book"),
    "family": ("#fff0f6", "#ff5c8a", "heart"),
    "food": ("#fff7df", "#ff9500", "apple"),
    "friends": ("#fff0f6", "#ff5c8a", "heart"),
    "games": ("#eef8ff", "#2481cc", "game"),
    "grammar": ("#eef8ff", "#2481cc", "book"),
    "health": ("#fff3e6", "#ff7a45", "heart"),
    "hobbies": ("#f4f0ff", "#7c5cff", "game"),
    "home": ("#eefaf8", "#2ec4b6", "home"),
    "jobs": ("#eef8ff", "#2481cc", "book"),
    "learning": ("#eef8ff", "#2481cc", "book"),
    "music": ("#f4f0ff", "#7c5cff", "music"),
    "nature": ("#ecfbef", "#34c759", "sun"),
    "places": ("#eefaf8", "#2ec4b6", "home"),
    "reading": ("#eef8ff", "#2481cc", "book"),
    "school": ("#eef8ff", "#2481cc", "book"),
    "science": ("#eefaf8", "#2ec4b6", "atom"),
    "speaking": ("#eef8ff", "#2481cc", "bubble"),
    "sports": ("#fff7df", "#ff9500", "ball"),
    "stories": ("#f4f0ff", "#7c5cff", "book"),
    "study": ("#eef8ff", "#2481cc", "book"),
    "technology": ("#eef8ff", "#2481cc", "laptop"),
    "time": ("#f2efff", "#7c5cff", "clock"),
    "toys": ("#fff7df", "#ff9500", "game"),
    "transport": ("#eef8ff", "#2481cc", "plane"),
    "travel": ("#eef8ff", "#2481cc", "plane"),
    "work": ("#eef8ff", "#2481cc", "book"),
}


FALLBACK_IMAGE_ICONS = (
    "apple", "paw", "book", "sun", "plane", "home", "game", "laptop",
    "music", "heart", "shirt", "ball", "bubble", "atom", "clock",
)

WORD_ICON_OVERRIDES = {
    "airport": "plane",
    "apple": "apple",
    "baby": "person",
    "banana": "banana",
    "basket": "basket",
    "ball": "ball",
    "beach": "beach",
    "bedroom": "bed",
    "bike": "bike",
    "book": "book",
    "board": "book",
    "boat": "boat",
    "bottle": "bottle",
    "box": "box",
    "bread": "bread",
    "bus": "bus",
    "cake": "cake",
    "camera": "camera",
    "car": "car",
    "cat": "paw",
    "chair": "chair",
    "cheese": "cheese",
    "classroom": "book",
    "clock": "clock",
    "cloud": "cloud",
    "coat": "shirt",
    "computer": "laptop",
    "cookie": "cookie",
    "cup": "cup",
    "dog": "paw",
    "desk": "table",
    "dictionary": "book",
    "dress": "shirt",
    "bird": "paw",
    "duck": "paw",
    "egg": "egg",
    "email": "laptop",
    "farm": "farm",
    "fish": "paw",
    "flower": "flower",
    "folder": "book",
    "football": "ball",
    "frog": "paw",
    "game": "game",
    "garden": "tree",
    "goat": "paw",
    "grandma": "person",
    "grandpa": "person",
    "guitar": "guitar",
    "hat": "shirt",
    "home": "home",
    "homework": "book",
    "horse": "paw",
    "hospital": "hospital",
    "house": "home",
    "juice": "cup",
    "kite": "kite",
    "kitchen": "home",
    "lamp": "lamp",
    "leaf": "tree",
    "lesson": "book",
    "lion": "paw",
    "milk": "milk",
    "moon": "moon",
    "mouse": "paw",
    "movie": "camera",
    "music": "music",
    "notebook": "book",
    "orange": "orange",
    "page": "book",
    "park": "tree",
    "pen": "pencil",
    "pencil": "pencil",
    "phone": "laptop",
    "picture": "camera",
    "pig": "paw",
    "plane": "plane",
    "playground": "game",
    "postcard": "postcard",
    "rabbit": "paw",
    "rain": "rain",
    "river": "river",
    "robot": "robot",
    "school": "book",
    "shoe": "shirt",
    "shirt": "shirt",
    "skateboard": "skateboard",
    "song": "music",
    "star": "star",
    "story": "book",
    "sun": "sun",
    "table": "table",
    "teacher": "person",
    "ticket": "ticket",
    "time": "clock",
    "toy": "game",
    "train": "train",
    "tree": "tree",
    "village": "home",
    "window": "window",
}

PERSON_WORDS = {
    "aunt", "brother", "classmate", "cousin", "dad", "doctor", "friend",
    "mom", "parent", "sister", "uncle",
}

WORD_ICON_OVERRIDES.update({word: "person" for word in PERSON_WORDS})


def _word_image_icon(word: str) -> str:
    return WORD_ICON_OVERRIDES.get(str(word or "").strip().lower(), "")


def _word_image_style(word: str, topic: str, seed: str):
    bg, color, icon = TOPIC_IMAGE_STYLES.get(topic, ("#eef8ff", "#2481cc", ""))
    icon = _word_image_icon(word) or icon
    if not icon or icon == "star":
        icon = FALLBACK_IMAGE_ICONS[int(seed[:2], 16) % len(FALLBACK_IMAGE_ICONS)]
    return bg, color, icon


def _topic_icon_svg(icon: str, color: str) -> str:
    if icon == "apple":
        return f"""
        <circle cx="160" cy="108" r="42" fill="{color}"/>
        <circle cx="130" cy="108" r="38" fill="{color}" opacity=".92"/>
        <path d="M158 62 C174 38 197 39 211 50 C194 74 177 76 158 62Z" fill="#34c759"/>
        <rect x="157" y="50" width="8" height="25" rx="4" fill="#8a5a2b"/>"""
    if icon == "banana":
        return f"""
        <path d="M107 92 C125 186 220 232 305 151 C241 179 170 154 145 72 C132 72 117 78 107 92Z" fill="{color}"/>
        <path d="M111 91 C132 171 220 204 288 153" fill="none" stroke="#fff" stroke-width="10" opacity=".46" stroke-linecap="round"/>
        <path d="M139 69 l-28 16 M306 151 l24 5" stroke="#8a5a2b" stroke-width="10" stroke-linecap="round"/>"""
    if icon == "bread":
        return f"""
        <path d="M100 139 C100 84 132 52 196 52 C260 52 292 84 292 139 V220 H100Z" fill="{color}"/>
        <path d="M124 143 C124 103 146 78 196 78 C246 78 268 103 268 143" fill="none" stroke="#fff" stroke-width="9" opacity=".42"/>
        <path d="M122 171 h150" stroke="#8a5a2b" stroke-width="8" opacity=".35" stroke-linecap="round"/>"""
    if icon == "cake":
        return f"""
        <rect x="100" y="126" width="192" height="102" rx="22" fill="{color}"/>
        <path d="M100 151 C128 132 145 171 174 151 C204 130 219 171 248 151 C270 136 283 146 292 151" fill="#fff" opacity=".78"/>
        <path d="M196 72 v54" stroke="{color}" stroke-width="12" stroke-linecap="round"/>
        <circle cx="196" cy="62" r="14" fill="#ffcc00"/>"""
    if icon == "cheese":
        return f"""
        <path d="M88 185 L282 78 V220 H88Z" fill="{color}"/>
        <circle cx="174" cy="161" r="14" fill="#fff" opacity=".55"/>
        <circle cx="225" cy="133" r="11" fill="#fff" opacity=".5"/>
        <circle cx="238" cy="191" r="17" fill="#fff" opacity=".45"/>"""
    if icon == "cookie":
        return f"""
        <circle cx="196" cy="132" r="82" fill="{color}"/>
        <circle cx="161" cy="101" r="10" fill="#8a5a2b"/>
        <circle cx="218" cy="89" r="9" fill="#8a5a2b"/>
        <circle cx="230" cy="151" r="11" fill="#8a5a2b"/>
        <circle cx="174" cy="168" r="8" fill="#8a5a2b"/>"""
    if icon == "milk":
        return f"""
        <path d="M142 54 h88 l-13 46 v128 h-62 V100Z" fill="{color}"/>
        <path d="M155 116 h62 v72 h-62Z" fill="#fff" opacity=".88"/>
        <path d="M154 54 h74 l-17 25 h-41Z" fill="{color}" opacity=".7"/>"""
    if icon == "egg":
        return f"""
        <ellipse cx="196" cy="132" rx="68" ry="88" fill="{color}"/>
        <ellipse cx="176" cy="102" rx="18" ry="24" fill="#fff" opacity=".35"/>"""
    if icon == "orange":
        return f"""
        <circle cx="196" cy="132" r="76" fill="{color}"/>
        <path d="M195 61 C217 39 247 42 263 59 C240 81 217 83 195 61Z" fill="#34c759"/>
        <path d="M138 132 h116 M196 74 v116 M154 88 C181 105 213 105 239 88 M154 176 C181 159 213 159 239 176" stroke="#fff" stroke-width="7" opacity=".45" fill="none"/>"""
    if icon == "cup":
        return f"""
        <path d="M118 82 h132 v92 c0 37-30 67-66 67s-66-30-66-67Z" fill="{color}"/>
        <path d="M250 111 h33 c21 0 38 17 38 38s-17 38-38 38h-33v-24h31c8 0 14-6 14-14s-6-14-14-14h-31Z" fill="{color}" opacity=".72"/>
        <path d="M142 111 h84" stroke="#fff" stroke-width="9" opacity=".72" stroke-linecap="round"/>"""
    if icon == "basket":
        return f"""
        <path d="M102 120 h188 l-24 98 H126Z" fill="{color}"/>
        <path d="M145 120 C151 76 241 76 247 120" fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round"/>
        <path d="M128 154 h136 M138 188 h116 M166 123 v92 M220 123 v92" stroke="#fff" stroke-width="7" opacity=".55"/>"""
    if icon == "box":
        return f"""
        <path d="M100 104 h196 v132 H100Z" fill="{color}"/>
        <path d="M100 104 l50-42 h146 l-46 42Z" fill="{color}" opacity=".7"/>
        <path d="M250 104 l46-42 v132 l-46 42Z" fill="{color}" opacity=".55"/>
        <path d="M150 62 l50 42 v132" stroke="#fff" stroke-width="8" opacity=".45"/>"""
    if icon == "paw":
        return f"""
        <circle cx="144" cy="117" r="31" fill="{color}"/>
        <circle cx="106" cy="83" r="17" fill="{color}" opacity=".88"/>
        <circle cx="138" cy="67" r="18" fill="{color}" opacity=".88"/>
        <circle cx="174" cy="75" r="17" fill="{color}" opacity=".88"/>
        <circle cx="201" cy="101" r="16" fill="{color}" opacity=".88"/>"""
    if icon == "book":
        return f"""
        <path d="M88 62 h82 c17 0 30 13 30 30 v82 h-82 c-17 0-30-13-30-30Z" fill="{color}"/>
        <path d="M200 62 h72 c17 0 30 13 30 30 v82 h-72 c-17 0-30-13-30-30Z" fill="{color}" opacity=".72"/>
        <path d="M200 78 v92" stroke="#fff" stroke-width="8" stroke-linecap="round"/>"""
    if icon == "sun":
        return f"""
        <circle cx="176" cy="102" r="43" fill="{color}"/>
        <path d="M70 180 C118 130 170 133 216 180Z" fill="#34c759" opacity=".55"/>
        <path d="M150 180 C198 123 260 126 314 180Z" fill="#2ec4b6" opacity=".42"/>"""
    if icon == "moon":
        return f"""
        <path d="M238 51 C190 67 158 112 158 164 C158 207 181 244 215 264 C146 260 94 204 94 135 C94 65 148 9 218 5 C204 17 196 35 196 58 C196 94 225 123 261 123 C274 123 287 119 297 112 C291 144 270 174 238 193 C255 146 255 93 238 51Z" fill="{color}"/>
        <circle cx="292" cy="58" r="13" fill="{color}" opacity=".55"/>
        <circle cx="320" cy="100" r="8" fill="{color}" opacity=".5"/>"""
    if icon == "star":
        return f"""
        <path d="M196 52 l24 51 l56 8 l-40 40 l9 56 l-49-26 l-50 26 l10-56 l-41-40 l56-8Z" fill="{color}"/>"""
    if icon == "cloud":
        return f"""
        <path d="M104 170 h174 c31 0 56-25 56-56s-25-56-56-56c-8 0-16 2-23 5C239 36 210 20 177 20c-47 0-86 36-90 82c-31 6-55 34-55 67c0 38 31 69 72 69Z" fill="{color}"/>
        <path d="M102 175 h176" stroke="#fff" stroke-width="12" opacity=".6" stroke-linecap="round"/>"""
    if icon == "rain":
        return f"""
        <path d="M111 119 h169c26 0 47-21 47-47s-21-47-47-47c-8 0-16 2-23 6c-15-19-39-31-66-31c-43 0-78 32-83 73c-29 2-52 26-52 56c0 31 25 56 55 56Z" fill="{color}"/>
        <path d="M126 211 l-18 42 M190 211 l-18 42 M254 211 l-18 42" stroke="{color}" stroke-width="13" stroke-linecap="round" opacity=".78"/>"""
    if icon == "tree":
        return f"""
        <circle cx="178" cy="82" r="49" fill="{color}"/>
        <circle cx="138" cy="125" r="44" fill="{color}" opacity=".88"/>
        <circle cx="221" cy="126" r="48" fill="{color}" opacity=".92"/>
        <rect x="168" y="142" width="28" height="87" rx="10" fill="#8a5a2b"/>
        <path d="M114 227 h166" stroke="#34c759" stroke-width="18" stroke-linecap="round" opacity=".45"/>"""
    if icon == "flower":
        return f"""
        <circle cx="196" cy="122" r="22" fill="#ffcc00"/>
        <circle cx="196" cy="78" r="30" fill="{color}"/>
        <circle cx="196" cy="166" r="30" fill="{color}" opacity=".86"/>
        <circle cx="152" cy="122" r="30" fill="{color}" opacity=".92"/>
        <circle cx="240" cy="122" r="30" fill="{color}" opacity=".92"/>
        <path d="M196 180 v70" stroke="#34c759" stroke-width="15" stroke-linecap="round"/>
        <path d="M195 214 C158 196 139 211 122 240" fill="none" stroke="#34c759" stroke-width="12" stroke-linecap="round"/>"""
    if icon == "river":
        return f"""
        <path d="M80 76 C142 100 151 145 122 190 C175 171 214 197 233 252 C246 198 290 165 330 150" fill="none" stroke="{color}" stroke-width="34" stroke-linecap="round"/>
        <path d="M75 204 C139 174 202 203 250 240" fill="none" stroke="#34c759" stroke-width="18" stroke-linecap="round" opacity=".42"/>"""
    if icon == "beach":
        return f"""
        <path d="M72 205 C133 160 237 160 320 210 V252 H72Z" fill="#ffcc66"/>
        <path d="M70 181 C146 151 244 151 326 181" stroke="{color}" stroke-width="16" stroke-linecap="round" fill="none"/>
        <circle cx="128" cy="72" r="34" fill="{color}"/>"""
    if icon == "farm":
        return f"""
        <path d="M88 135 l78-62 l78 62 v89 H88Z" fill="{color}"/>
        <path d="M142 224 v-58 h48 v58" fill="#fff" opacity=".9"/>
        <path d="M68 245 C132 215 221 215 306 245" stroke="#34c759" stroke-width="20" stroke-linecap="round"/>"""
    if icon == "plane":
        return f"""
        <path d="M74 132 L305 55 L242 188 L195 142 L135 181 L157 121Z" fill="{color}"/>
        <path d="M157 121 L305 55 L195 142" fill="none" stroke="#fff" stroke-width="8" stroke-linecap="round" opacity=".75"/>"""
    if icon == "car":
        return f"""
        <path d="M90 132 l34-54 h144 l34 54 v54 H90Z" fill="{color}"/>
        <path d="M139 94 h114 l20 38 H118Z" fill="#fff" opacity=".72"/>
        <circle cx="133" cy="190" r="24" fill="#1f2933"/>
        <circle cx="259" cy="190" r="24" fill="#1f2933"/>"""
    if icon == "bus":
        return f"""
        <rect x="82" y="70" width="228" height="138" rx="25" fill="{color}"/>
        <path d="M108 96 h176 v55 H108Z" fill="#fff" opacity=".78"/>
        <path d="M164 96 v55 M224 96 v55" stroke="{color}" stroke-width="8" opacity=".55"/>
        <circle cx="130" cy="211" r="22" fill="#1f2933"/>
        <circle cx="262" cy="211" r="22" fill="#1f2933"/>"""
    if icon == "train":
        return f"""
        <rect x="108" y="54" width="176" height="162" rx="26" fill="{color}"/>
        <path d="M132 82 h128 v58 H132Z" fill="#fff" opacity=".78"/>
        <path d="M150 237 l28-35 M242 237 l-28-35" stroke="{color}" stroke-width="14" stroke-linecap="round"/>
        <circle cx="154" cy="172" r="12" fill="#fff"/>
        <circle cx="238" cy="172" r="12" fill="#fff"/>"""
    if icon == "bike":
        return f"""
        <circle cx="123" cy="184" r="45" fill="none" stroke="{color}" stroke-width="13"/>
        <circle cx="270" cy="184" r="45" fill="none" stroke="{color}" stroke-width="13"/>
        <path d="M123 184 l52-70 h48 l47 70 M175 114 l36 70 h-88" fill="none" stroke="{color}" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M210 91 h44" stroke="{color}" stroke-width="12" stroke-linecap="round"/>"""
    if icon == "skateboard":
        return f"""
        <path d="M91 159 C139 196 253 196 301 159" fill="none" stroke="{color}" stroke-width="24" stroke-linecap="round"/>
        <circle cx="132" cy="198" r="20" fill="#1f2933"/>
        <circle cx="260" cy="198" r="20" fill="#1f2933"/>
        <path d="M118 145 C164 165 228 165 274 145" fill="none" stroke="#fff" stroke-width="8" opacity=".48" stroke-linecap="round"/>"""
    if icon == "boat":
        return f"""
        <path d="M86 153 h222 l-38 64 H124Z" fill="{color}"/>
        <path d="M183 58 v96" stroke="{color}" stroke-width="13" stroke-linecap="round"/>
        <path d="M193 67 l78 70 h-78Z" fill="{color}" opacity=".72"/>
        <path d="M75 232 C122 214 168 214 215 232 C255 247 293 247 330 232" fill="none" stroke="#2ec4b6" stroke-width="13" stroke-linecap="round"/>"""
    if icon == "home":
        return f"""
        <path d="M88 132 L184 58 L280 132 V210 H106 V132Z" fill="{color}"/>
        <path d="M154 210 V152 H214 V210" fill="#fff" opacity=".9"/>
        <path d="M74 136 L184 50 L294 136" fill="none" stroke="{color}" stroke-width="18" stroke-linecap="round"/>"""
    if icon == "chair":
        return f"""
        <path d="M122 70 h130 v88 H122Z" fill="{color}"/>
        <path d="M108 151 h158 v32 H108Z" fill="{color}" opacity=".78"/>
        <path d="M132 183 v58 M242 183 v58" stroke="{color}" stroke-width="15" stroke-linecap="round"/>"""
    if icon == "table":
        return f"""
        <path d="M92 106 h208 v38 H92Z" fill="{color}"/>
        <path d="M122 144 v90 M270 144 v90" stroke="{color}" stroke-width="16" stroke-linecap="round"/>
        <path d="M124 184 h146" stroke="{color}" stroke-width="12" opacity=".55"/>"""
    if icon == "lamp":
        return f"""
        <path d="M139 62 h114 l34 88 H105Z" fill="{color}"/>
        <path d="M196 150 v72" stroke="{color}" stroke-width="16" stroke-linecap="round"/>
        <path d="M142 228 h108" stroke="{color}" stroke-width="16" stroke-linecap="round"/>
        <path d="M132 150 h128" stroke="#fff" stroke-width="8" opacity=".56"/>"""
    if icon == "window":
        return f"""
        <rect x="104" y="68" width="184" height="156" rx="16" fill="{color}"/>
        <path d="M196 72 v148 M108 146 h176" stroke="#fff" stroke-width="11" opacity=".86"/>
        <path d="M88 238 h216" stroke="{color}" stroke-width="15" stroke-linecap="round" opacity=".65"/>"""
    if icon == "bed":
        return f"""
        <path d="M90 112 h92 c24 0 43 19 43 43 v34 H90Z" fill="{color}"/>
        <path d="M90 82 h42 v73 H90Z" fill="{color}" opacity=".72"/>
        <path d="M86 188 h226 v45" stroke="{color}" stroke-width="17" stroke-linecap="round"/>
        <rect x="142" y="122" width="56" height="33" rx="13" fill="#fff" opacity=".75"/>"""
    if icon == "bottle":
        return f"""
        <path d="M166 52 h60 v37 l25 36 v102 c0 18-15 33-33 33h-44c-18 0-33-15-33-33V125l25-36Z" fill="{color}"/>
        <rect x="173" y="51" width="46" height="23" rx="8" fill="{color}" opacity=".72"/>
        <path d="M158 144 h76 v60 h-76Z" fill="#fff" opacity=".72"/>"""
    if icon == "game":
        return f"""
        <rect x="88" y="94" width="216" height="92" rx="38" fill="{color}"/>
        <circle cx="144" cy="139" r="13" fill="#fff"/>
        <path d="M128 139 h32 M144 123 v32" stroke="#fff" stroke-width="8" stroke-linecap="round"/>
        <circle cx="244" cy="128" r="10" fill="#fff"/>
        <circle cx="270" cy="151" r="10" fill="#fff"/>"""
    if icon == "robot":
        return f"""
        <rect x="108" y="86" width="176" height="126" rx="30" fill="{color}"/>
        <path d="M196 86 v-38" stroke="{color}" stroke-width="14" stroke-linecap="round"/>
        <circle cx="156" cy="142" r="13" fill="#fff"/>
        <circle cx="236" cy="142" r="13" fill="#fff"/>
        <path d="M162 181 h68" stroke="#fff" stroke-width="10" stroke-linecap="round"/>"""
    if icon == "kite":
        return f"""
        <path d="M198 54 l76 88 l-76 88 l-76-88Z" fill="{color}"/>
        <path d="M198 54 v176 M122 142 h152" stroke="#fff" stroke-width="8" opacity=".72"/>
        <path d="M198 230 C168 254 229 274 196 302" fill="none" stroke="{color}" stroke-width="8" stroke-linecap="round"/>"""
    if icon == "laptop":
        return f"""
        <rect x="95" y="72" width="202" height="122" rx="15" fill="{color}"/>
        <rect x="118" y="94" width="156" height="78" rx="8" fill="#fff" opacity=".88"/>
        <path d="M70 206 h252 l-28 31 H98Z" fill="{color}" opacity=".72"/>"""
    if icon == "camera":
        return f"""
        <rect x="90" y="92" width="212" height="132" rx="28" fill="{color}"/>
        <path d="M139 92 l19-29 h76 l19 29Z" fill="{color}" opacity=".75"/>
        <circle cx="196" cy="158" r="43" fill="#fff" opacity=".86"/>
        <circle cx="196" cy="158" r="24" fill="{color}"/>
        <circle cx="268" cy="121" r="10" fill="#fff"/>"""
    if icon == "postcard":
        return f"""
        <rect x="92" y="78" width="208" height="134" rx="18" fill="{color}"/>
        <path d="M116 104 h72 M116 132 h72 M116 160 h48" stroke="#fff" stroke-width="9" opacity=".75" stroke-linecap="round"/>
        <rect x="220" y="104" width="48" height="40" rx="8" fill="#fff" opacity=".78"/>
        <path d="M212 82 v126" stroke="#fff" stroke-width="7" opacity=".42"/>"""
    if icon == "ticket":
        return f"""
        <path d="M86 116 h220 v39 c-17 5-29 20-29 39s12 34 29 39v35H86v-35c17-5 29-20 29-39s-12-34-29-39Z" fill="{color}"/>
        <path d="M164 127 v130" stroke="#fff" stroke-width="8" opacity=".55" stroke-dasharray="12 12"/>
        <path d="M194 157 h66 M194 195 h48" stroke="#fff" stroke-width="9" opacity=".72" stroke-linecap="round"/>"""
    if icon == "music":
        return f"""
        <path d="M210 62 v126" stroke="{color}" stroke-width="18" stroke-linecap="round"/>
        <path d="M210 70 l74 24 v34 l-74-24Z" fill="{color}"/>
        <circle cx="174" cy="190" r="34" fill="{color}"/>"""
    if icon == "guitar":
        return f"""
        <path d="M155 119 C128 106 99 121 89 149 C77 183 103 218 139 213 C145 248 184 269 214 247 C238 230 240 198 221 178 C254 169 267 132 247 105 C229 81 196 77 174 95 Z" fill="{color}"/>
        <path d="M218 98 l72-55" stroke="{color}" stroke-width="16" stroke-linecap="round"/>
        <circle cx="164" cy="169" r="25" fill="#fff" opacity=".86"/>
        <path d="M140 204 L260 72" stroke="#fff" stroke-width="6" opacity=".72"/>"""
    if icon == "heart":
        return f"""
        <path d="M196 199 C108 145 83 107 111 75 C136 46 176 59 196 91 C216 59 256 46 281 75 C309 107 284 145 196 199Z" fill="{color}"/>"""
    if icon == "person":
        return f"""
        <circle cx="196" cy="88" r="43" fill="{color}"/>
        <path d="M105 235 C118 178 151 147 196 147 C241 147 274 178 287 235Z" fill="{color}" opacity=".78"/>
        <path d="M151 102 C170 123 224 123 242 102" stroke="#fff" stroke-width="8" opacity=".6" stroke-linecap="round"/>"""
    if icon == "hospital":
        return f"""
        <path d="M100 86 h192 v146 H100Z" fill="{color}"/>
        <path d="M174 114 h44 v32 h32 v44 h-32 v32 h-44 v-32 h-32 v-44 h32Z" fill="#fff"/>
        <path d="M82 232 h228" stroke="{color}" stroke-width="16" stroke-linecap="round" opacity=".7"/>"""
    if icon == "shirt":
        return f"""
        <path d="M132 62 l37 22 h54 l37-22 l54 50 l-38 42 l-24-21 v94 H140 v-94 l-24 21 l-38-42Z" fill="{color}"/>"""
    if icon == "pencil":
        return f"""
        <path d="M105 215 l29-75 L258 57 l51 51 l-123 83Z" fill="{color}"/>
        <path d="M258 57 l31-21 l41 41 l-21 31Z" fill="#8a5a2b"/>
        <path d="M105 215 l64-24 l-40-40Z" fill="#ffcc66"/>
        <path d="M142 140 l51 51" stroke="#fff" stroke-width="9" opacity=".7"/>"""
    if icon == "ball":
        return f"""
        <circle cx="196" cy="130" r="76" fill="{color}"/>
        <path d="M137 82 C171 103 217 103 255 82 M132 178 C171 154 222 154 260 178 M196 55 C180 91 180 165 196 205 M196 55 C214 94 214 166 196 205" fill="none" stroke="#fff" stroke-width="7" opacity=".78"/>"""
    if icon == "bubble":
        return f"""
        <path d="M95 82 h202 c23 0 41 18 41 41 v30 c0 23-18 41-41 41 h-86 l-62 42 v-42 H95 c-23 0-41-18-41-41 v-30 c0-23 18-41 41-41Z" fill="{color}"/>
        <circle cx="142" cy="138" r="9" fill="#fff"/><circle cx="196" cy="138" r="9" fill="#fff"/><circle cx="250" cy="138" r="9" fill="#fff"/>"""
    if icon == "atom":
        return f"""
        <circle cx="196" cy="130" r="16" fill="{color}"/>
        <ellipse cx="196" cy="130" rx="100" ry="35" fill="none" stroke="{color}" stroke-width="10"/>
        <ellipse cx="196" cy="130" rx="100" ry="35" fill="none" stroke="{color}" stroke-width="10" transform="rotate(60 196 130)"/>
        <ellipse cx="196" cy="130" rx="100" ry="35" fill="none" stroke="{color}" stroke-width="10" transform="rotate(120 196 130)"/>"""
    if icon == "clock":
        return f"""
        <circle cx="196" cy="130" r="76" fill="{color}"/>
        <path d="M196 84 v51 l42 25" stroke="#fff" stroke-width="12" stroke-linecap="round" fill="none"/>"""
    return f"""
    <path d="M196 52 l24 51 l56 8 l-40 40 l9 56 l-49-26 l-50 26 l10-56 l-41-40 l56-8Z" fill="{color}"/>"""


def _word_image_svg(word: str, topic: str) -> str:
    clean_word = " ".join(str(word or "word").split())[:48]
    clean_topic = " ".join(str(topic or "basic").split())[:32]
    seed = hashlib.sha1(f"{clean_word}:{clean_topic}".encode("utf-8")).hexdigest()
    bg, color, icon = _word_image_style(clean_word, clean_topic, seed)
    accent = f"#{seed[:6]}"
    icon_svg = _topic_icon_svg(icon, color)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512" role="img" aria-label="word picture">
  <rect width="512" height="512" rx="54" fill="{bg}"/>
  <circle cx="426" cy="78" r="54" fill="{accent}" opacity=".14"/>
  <circle cx="80" cy="420" r="78" fill="{color}" opacity=".10"/>
  <circle cx="256" cy="256" r="168" fill="#fff" opacity=".72"/>
  <g transform="translate(60 126) scale(1.02)">{icon_svg}</g>
</svg>"""


def _vocabulary_visual_svg(word: str, topic: str, visual_type: str) -> str:
    clean_word = " ".join(str(word or "word").split()).lower()[:48]
    clean_topic = " ".join(str(topic or "basic").split()).lower()[:32]
    clean_type = " ".join(str(visual_type or "object").split()).lower()
    seed = hashlib.sha1(f"{clean_word}:{clean_topic}:{clean_type}".encode("utf-8")).hexdigest()
    bg, color, icon = _word_image_style(clean_word, clean_topic, seed)
    accent = f"#{seed[:6]}"
    icon_svg = _topic_icon_svg(icon, color)

    def panel(x: int, y: int, w: int = 156, h: int = 210) -> str:
        return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="28" fill="#fff" opacity=".82" stroke="{color}" stroke-opacity=".14"/>'

    if clean_type == "object":
        return _word_image_svg(clean_word, clean_topic)
    if clean_type == "action":
        scene = f"""
        <circle cx="190" cy="128" r="36" fill="{color}"/>
        <path d="M190 164 l-38 70 M190 164 l50 58 M188 178 l-65 10 M188 178 l76-22" stroke="{color}" stroke-width="18" stroke-linecap="round"/>
        <path d="M78 218 C124 202 166 202 214 218 C250 230 294 230 334 218" fill="none" stroke="#34c759" stroke-width="14" opacity=".55" stroke-linecap="round"/>
        <path d="M92 124 h46 M78 164 h54 M280 106 h42" stroke="{accent}" stroke-width="12" opacity=".42" stroke-linecap="round"/>
        <g transform="translate(214 62) scale(.42)">{icon_svg}</g>"""
    elif clean_type == "contrast":
        scene = f"""
        <circle cx="156" cy="174" r="82" fill="{color}" opacity=".86"/>
        <circle cx="286" cy="205" r="34" fill="{accent}" opacity=".62"/>
        <path d="M108 274 h220" stroke="#34c759" stroke-width="14" opacity=".45" stroke-linecap="round"/>
        <path d="M130 130 C146 106 176 106 193 130" fill="none" stroke="#fff" stroke-width="9" opacity=".6" stroke-linecap="round"/>"""
    elif clean_type == "emotion":
        mouth = "M162 174 C178 206 226 206 242 174" if clean_word not in {"sad", "angry", "scared", "worried", "tired"} else "M162 199 C182 176 222 176 242 199"
        brows = "M139 120 l45-12 M208 108 l45 12" if clean_word in {"angry", "worried"} else "M139 110 h45 M208 110 h45"
        scene = f"""
        <circle cx="196" cy="164" r="96" fill="{color}" opacity=".9"/>
        <circle cx="160" cy="148" r="12" fill="#1f2933"/>
        <circle cx="232" cy="148" r="12" fill="#1f2933"/>
        <path d="{mouth}" fill="none" stroke="#1f2933" stroke-width="12" stroke-linecap="round"/>
        <path d="{brows}" stroke="#1f2933" stroke-width="9" stroke-linecap="round" opacity=".7"/>
        <circle cx="302" cy="88" r="34" fill="{accent}" opacity=".18"/>"""
    elif clean_type == "spatial_relation":
        positions = {
            "in": (180, 160),
            "on": (190, 88),
            "under": (190, 248),
            "behind": (146, 156),
            "between": (196, 160),
            "above": (190, 70),
        }
        bx, by = positions.get(clean_word, (196, 160))
        extra_box = '<rect x="252" y="128" width="90" height="90" rx="16" fill="#bfe7ff" stroke="#2481cc" stroke-width="8" opacity=".72"/>' if clean_word == "between" else ""
        scene = f"""
        <rect x="112" y="126" width="132" height="112" rx="22" fill="#dff3ff" stroke="{color}" stroke-width="10"/>
        {extra_box}
        <circle cx="{bx}" cy="{by}" r="34" fill="{accent}"/>
        <path d="M92 276 h230" stroke="#34c759" stroke-width="14" opacity=".42" stroke-linecap="round"/>"""
    elif clean_type == "situation":
        if clean_word == "honest":
            prop = '<rect x="186" y="166" width="48" height="34" rx="8" fill="#8a5a2b"/><circle cx="222" cy="176" r="6" fill="#ffcc00"/>'
        elif clean_word == "careful":
            prop = '<path d="M184 150 h54 v74 c0 15-12 27-27 27s-27-12-27-27Z" fill="#bfe7ff" stroke="#2481cc" stroke-width="7"/><path d="M190 184 h42" stroke="#fff" stroke-width="8" opacity=".8"/>'
        elif clean_word == "proud":
            prop = '<rect x="168" y="135" width="74" height="60" rx="10" fill="#fff" stroke="#ffcc00" stroke-width="8"/><circle cx="205" cy="165" r="15" fill="#ffcc00"/>'
        elif clean_word == "worried":
            prop = '<circle cx="218" cy="152" r="38" fill="#fff" stroke="#7c5cff" stroke-width="8"/><path d="M218 130 v25 l18 12" stroke="#7c5cff" stroke-width="8" stroke-linecap="round"/>'
        else:
            prop = '<path d="M196 158 C154 126 113 164 144 202 C163 226 186 223 196 245 C206 223 229 226 248 202 C279 164 238 126 196 158Z" fill="#ff5c8a"/>'
        scene = f"""
        <circle cx="136" cy="124" r="34" fill="{color}"/>
        <path d="M82 248 C92 196 111 168 136 168 C164 168 184 197 194 248Z" fill="{color}" opacity=".78"/>
        <circle cx="270" cy="124" r="34" fill="{accent}" opacity=".7"/>
        <path d="M216 248 C226 196 245 168 270 168 C298 168 318 197 328 248Z" fill="{accent}" opacity=".5"/>
        {prop}
        <path d="M118 270 h172" stroke="#34c759" stroke-width="13" opacity=".38" stroke-linecap="round"/>"""
    elif clean_type == "cause_effect":
        scene = f"""
        {panel(74, 66)}{panel(244, 66)}
        <path d="M104 120 h95c21 0 38-17 38-38s-17-38-38-38c-7 0-14 2-20 5c-12-18-33-29-56-29c-36 0-65 27-69 62c-24 3-42 23-42 47c0 26 21 47 47 47Z" fill="{color}" opacity=".78"/>
        <path d="M112 190 l-13 31 M162 190 l-13 31 M210 190 l-13 31" stroke="{color}" stroke-width="9" stroke-linecap="round"/>
        <circle cx="306" cy="122" r="31" fill="{accent}" opacity=".72"/>
        <path d="M306 153 v58 M306 170 l-42 36 M306 170 l42 36" stroke="{accent}" stroke-width="13" stroke-linecap="round"/>
        <path d="M206 172 h48" stroke="#1f2933" stroke-width="10" opacity=".35" stroke-linecap="round"/>"""
    elif clean_type == "two_panel_comic":
        scene = f"""
        {panel(72, 58)}{panel(246, 58)}
        <path d="M104 116 h104c18 0 32-14 32-32s-14-32-32-32c-7 0-14 2-20 6c-11-16-29-26-50-26c-33 0-60 24-65 57" fill="{color}" opacity=".7"/>
        <path d="M114 170 l-12 30 M158 170 l-12 30 M202 170 l-12 30" stroke="{color}" stroke-width="8" stroke-linecap="round"/>
        <circle cx="320" cy="124" r="55" fill="#ffcc00"/>
        <circle cx="302" cy="110" r="7" fill="#1f2933"/><circle cx="338" cy="110" r="7" fill="#1f2933"/>
        <path d="M298 136 C311 154 334 154 347 136" fill="none" stroke="#1f2933" stroke-width="8" stroke-linecap="round"/>
        <path d="M224 162 h38" stroke="#1f2933" stroke-width="10" opacity=".22" stroke-linecap="round"/>"""
    elif clean_type == "grammar_diagram":
        scene = f"""
        <circle cx="156" cy="126" r="35" fill="{color}"/>
        <path d="M156 160 v68 M156 182 l-52 40 M156 182 l62 34" stroke="{color}" stroke-width="16" stroke-linecap="round"/>
        <circle cx="272" cy="196" r="48" fill="none" stroke="{accent}" stroke-width="14"/>
        <path d="M250 160 C262 128 301 128 314 160" fill="{accent}" opacity=".55"/>
        <path d="M245 106 C262 78 304 78 321 106" fill="none" stroke="{accent}" stroke-width="14" stroke-linecap="round"/>
        <path d="M103 262 h205" stroke="#34c759" stroke-width="14" opacity=".4" stroke-linecap="round"/>"""
    else:
        scene = f"""
        <rect x="102" y="86" width="188" height="140" rx="24" fill="#fff" stroke="{color}" stroke-width="10" opacity=".86"/>
        <circle cx="328" cy="118" r="38" fill="{accent}" opacity=".32"/>
        <path d="M138 132 h82 M138 170 h118" stroke="{color}" stroke-width="13" stroke-linecap="round" opacity=".28"/>
        <g transform="translate(144 142) scale(.38)">{icon_svg}</g>
        <path d="M92 260 h220" stroke="#34c759" stroke-width="14" opacity=".38" stroke-linecap="round"/>"""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512" role="img" aria-label="vocabulary visual scene">
  <rect width="512" height="512" rx="54" fill="{bg}"/>
  <circle cx="428" cy="80" r="58" fill="{accent}" opacity=".12"/>
  <circle cx="84" cy="418" r="82" fill="{color}" opacity=".09"/>
  <circle cx="256" cy="256" r="176" fill="#fff" opacity=".64"/>
  <g transform="translate(60 94) scale(1.02)">{scene}</g>
</svg>"""


# ---------- Middleware ----------
