"""표준노드링크(국가교통정보센터) 도로망에 단속 카메라를 붙여서, 앱이 "같은 도로인지" 판단할 수 있게 한다.

입력: 표준노드링크 zip (이 저장소 Release "nodelink"에 올린 파일). 안에 MOCT_LINK.shp/.dbf가 있다.
좌표계: ITRF2000 중부원점 (EPSG:5186과 같음, GRS80, 원점 38N 127E, 가산 200000/600000)

하는 일
1. 카메라(주정차 단속 CCTV, 경찰청 주정차·보호구역 카메라) 근처의 도로 구간(링크)만 남긴다.
2. 이름이 같은 도로가 이어지면 하나의 "도로"로 묶는다. (양방향 링크, 중앙분리대로 나뉜 차로도 같이)
3. 카메라마다 가장 가까운 도로를 붙인다.

앱은 차가 서 있는 도로(가장 가까운 링크)를 찾고, 그 도로에 붙은 카메라가 가까이 있을 때만 알려준다.
외부 라이브러리 없이 돈다. (shp/dbf 읽기, 좌표 변환을 직접 한다)
"""
import math
import struct
import zipfile
from collections import defaultdict

# 근처 링크를 남기는 거리(m). 차가 카메라에서 이만큼 안에 있을 때 도로를 비교하므로, 그보다 조금 넉넉하게.
PARKING_RANGE = 100     # 주정차 카메라: 같은 도로 100m 안이면 단속될 수 있다고 본다
ZONE_RANGE = 150        # 어린이보호구역 카메라: 같은 도로 150m 안이면 보호구역 도로일 가능성이 높다
SNAP = 25               # 차·카메라를 도로에 붙이는 최대 거리 (도로 폭 + GPS 오차)
KEEP_MARGIN = SNAP + 5

# ---------------------------------------------------------------- 좌표 변환 (횡메르카토르, GRS80)

A = 6378137.0
F = 1 / 298.257222101
E2 = F * (2 - F)
EP2 = E2 / (1 - E2)
LAT0, LON0 = math.radians(38.0), math.radians(127.0)
FE, FN, K0 = 200000.0, 600000.0, 1.0


def _meridian(phi):
    e4, e6 = E2 * E2, E2 * E2 * E2
    return A * ((1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
                - (3 * E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
                + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
                - (35 * e6 / 3072) * math.sin(6 * phi))


M0 = _meridian(LAT0)


def to_xy(lat, lon):
    """위도·경도 → 중부원점 x(동), y(북) m"""
    phi, lam = math.radians(lat), math.radians(lon)
    n = A / math.sqrt(1 - E2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = EP2 * math.cos(phi) ** 2
    a = (lam - LON0) * math.cos(phi)
    m = _meridian(phi)
    x = FE + K0 * n * (a + (1 - t + c) * a ** 3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * EP2) * a ** 5 / 120)
    y = FN + K0 * (m - M0 + n * math.tan(phi) * (a * a / 2 + (5 - t + 9 * c + 4 * c * c) * a ** 4 / 24
                                                  + (61 - 58 * t + t * t + 600 * c - 330 * EP2) * a ** 6 / 720))
    return x, y


def to_latlon(x, y):
    """중부원점 x, y → 위도·경도"""
    m = M0 + (y - FN) / K0
    mu = m / (A * (1 - E2 / 4 - 3 * E2 * E2 / 64 - 5 * E2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    n1 = A / math.sqrt(1 - E2 * math.sin(phi1) ** 2)
    t1 = math.tan(phi1) ** 2
    c1 = EP2 * math.cos(phi1) ** 2
    r1 = A * (1 - E2) / (1 - E2 * math.sin(phi1) ** 2) ** 1.5
    d = (x - FE) / (n1 * K0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * EP2) * d ** 4 / 24
                                               + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * EP2 - 3 * c1 * c1) * d ** 6 / 720)
    lon = LON0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
                  + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * EP2 + 24 * t1 * t1) * d ** 5 / 120) / math.cos(phi1)
    return math.degrees(lat), math.degrees(lon)

# ---------------------------------------------------------------- shp / dbf 읽기


def read_dbf(data, wanted):
    """dbf에서 원하는 항목만 순서대로 꺼낸다."""
    count, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields, pos, offset = {}, 32, 1
    while data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b"\0")[0].decode()
        length = data[pos + 16]
        fields[name] = (offset, length)
        offset += length
        pos += 32
    spans = [fields[name] for name in wanted]
    for i in range(count):
        base = header_len + i * record_len
        yield [data[base + o:base + o + l] for o, l in spans]


def read_shp(data):
    """polyline shp에서 링크마다 [(x, y), ...] (부분이 여러 개면 이어 붙인다)"""
    pos = 100
    end = len(data)
    while pos < end:
        _, length = struct.unpack(">ii", data[pos:pos + 8])
        content = pos + 8
        shape_type = struct.unpack("<i", data[content:content + 4])[0]
        if shape_type == 0:
            yield []
        else:
            num_parts, num_points = struct.unpack("<ii", data[content + 36:content + 44])
            points_at = content + 44 + 4 * num_parts
            flat = struct.unpack(f"<{2 * num_points}d", data[points_at:points_at + 16 * num_points])
            yield list(zip(flat[0::2], flat[1::2]))
        pos = content + length * 2

# ---------------------------------------------------------------- 기하


def point_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy)


def point_line(px, py, line):
    return min(point_segment(px, py, *line[i], *line[i + 1]) for i in range(len(line) - 1))


def simplify(line, tolerance=2.0):
    """더글라스-포이커로 점 수를 줄인다. (도로 모양은 2m 안에서 같게)"""
    if len(line) < 3:
        return line
    keep = [False] * len(line)
    keep[0] = keep[-1] = True
    stack = [(0, len(line) - 1)]
    while stack:
        i, j = stack.pop()
        best, index = 0.0, -1
        for k in range(i + 1, j):
            d = point_segment(*line[k], *line[i], *line[j])
            if d > best:
                best, index = d, k
        if best > tolerance:
            keep[index] = True
            stack += [(i, index), (index, j)]
    return [p for p, k in zip(line, keep) if k]

# ---------------------------------------------------------------- 만들기


def build(zip_path, targets):
    """targets: [(lat, lon, range_m), ...] 카메라 순서대로.
    돌려주는 것: (roads, target_roads, stats)
      roads: {"coords": 앞 점과의 차이(1e-5도 정수) [위도, 경도, ...], "lengths": 조각마다 점 수, "groups": 조각마다 도로 번호}
      target_roads: 카메라마다 붙은 도로 번호 (-1: 근처에 도로가 없음)"""
    cell = 250.0
    target_xy = [to_xy(lat, lon) for lat, lon, _ in targets]
    grid = defaultdict(list)
    for i, (x, y) in enumerate(target_xy):
        grid[(int(x // cell), int(y // cell))].append(i)

    with zipfile.ZipFile(zip_path) as z:
        def member(suffix):
            return next(n for n in z.namelist() if n.upper().endswith(suffix))
        shp = z.read(member("MOCT_LINK.SHP"))
        dbf = z.read(member("MOCT_LINK.DBF"))

    pieces = []        # (조각 [(x, y), ...], 도로 이름, 링크 번호)
    best = [(SNAP, -1)] * len(targets)  # 카메라마다 (거리, pieces 번호)
    total = 0
    reach_max = ZONE_RANGE + KEEP_MARGIN
    for link, (line, (name,)) in enumerate(zip(read_shp(shp), read_dbf(dbf, ["ROAD_NAME"]))):
        total += 1
        if len(line) < 2:
            continue
        xs = [p[0] for p in line]
        ys = [p[1] for p in line]
        cx0, cx1 = int((min(xs) - reach_max) // cell), int((max(xs) + reach_max) // cell)
        cy0, cy1 = int((min(ys) - reach_max) // cell), int((max(ys) + reach_max) // cell)
        near = [i for cx in range(cx0, cx1 + 1) for cy in range(cy0, cy1 + 1) for i in grid.get((cx, cy), ())]
        if not near:
            continue
        # 카메라 근처에 있는 부분만 남긴다. (긴 링크의 먼 부분은 버린다)
        keep = []
        for k in range(len(line) - 1):
            ax, ay = line[k]
            bx, by = line[k + 1]
            close = False
            for i in near:
                x, y = target_xy[i]
                d = point_segment(x, y, ax, ay, bx, by)
                if d <= targets[i][2] + KEEP_MARGIN:
                    close = True
                    if d < best[i][0]:
                        best[i] = (d, (link, k))
            keep.append(close)
        if not any(keep):
            continue
        label = name.decode("cp949", "replace").strip()
        k = 0
        while k < len(keep):
            if not keep[k]:
                k += 1
                continue
            j = k
            while j < len(keep) and keep[j]:
                j += 1
            pieces.append((line[k:j + 1], label, link, k, j))
            k = j

    # 도로 묶음: 이름이 같으면 같은 도로 (양방향 링크는 노드가 서로 달라서 이름으로 묶는다).
    # 카메라와 차를 100~200m 안에서만 비교하므로, 이름이 같은 다른 도로와 섞일 일은 거의 없다.
    # 이름이 없는 링크는 링크마다 따로.
    group_ids = {}
    piece_group = []
    for piece, label, link, k0, k1 in pieces:
        key = ("name", label) if label else ("link", link)
        piece_group.append(group_ids.setdefault(key, len(group_ids)))

    # 카메라마다 붙은 도로 번호
    piece_of = defaultdict(list)
    for number, (_, _, link, k0, k1) in enumerate(pieces):
        piece_of[link].append((k0, k1, number))
    target_roads = []
    for distance, where in best:
        if where == -1:
            target_roads.append(-1)
            continue
        link, k = where
        number = next(n for k0, k1, n in piece_of[link] if k0 <= k < k1)
        target_roads.append(piece_group[number])

    # 파일을 작게: 같은 도로의 조각 중 끝과 시작이 맞닿은 것은 하나의 선으로 잇고,
    # 가까운 것끼리 이어서 쓴다. (점은 앞 점과의 차이로 쓰므로 가까울수록 작다)
    by_group = defaultdict(list)
    for number, (piece, *_rest) in enumerate(pieces):
        by_group[piece_group[number]].append([(round(x, 1), round(y, 1)) for x, y in piece])
    lines = []   # (도로 번호, 선)
    for group, items in by_group.items():
        starts = defaultdict(list)
        for index, piece in enumerate(items):
            starts[piece[0]].append(index)
        used = [False] * len(items)
        ends = {piece[-1] for piece in items}
        # 다른 조각이 이어 들어오지 않는 조각부터 시작한다.
        order = sorted(range(len(items)), key=lambda i: items[i][0] in ends)
        for index in order:
            if used[index]:
                continue
            used[index] = True
            line = list(items[index])
            while True:
                nxt = next((j for j in starts.get(line[-1], ()) if not used[j]), None)
                if nxt is None:
                    break
                used[nxt] = True
                line += items[nxt][1:]
            lines.append((group, line))
    lines.sort(key=lambda item: (int(item[1][0][1] // 2000), int(item[1][0][0] // 2000)))

    coords, lengths, groups = [], [], []
    last_lat = last_lon = 0
    for group, line in lines:
        simple = simplify(line)
        groups.append(group)
        lengths.append(len(simple))
        for x, y in simple:
            lat, lon = to_latlon(x, y)
            ilat, ilon = round(lat * 1e5), round(lon * 1e5)
            coords += [ilat - last_lat, ilon - last_lon]   # 앞 점과의 차이 (1e-5도 단위, 약 1m)
            last_lat, last_lon = ilat, ilon

    stats = {
        "links": total, "pieces": len(lengths),
        "roads": len(group_ids), "points": len(coords) // 2,
        "attached": sum(r >= 0 for r in target_roads), "targets": len(targets),
    }
    return {"coords": coords, "lengths": lengths, "groups": groups}, target_roads, stats


# ---------------------------------------------------------------- 파일로 쓰기


def _varint(value, out):
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return


def _zigzag(value):
    return value * 2 if value >= 0 else -value * 2 - 1


def encode(roads, cctv_roads, camera_roads, updated_at):
    """앱이 빠르게 읽도록 작은 바이너리로 쓴다. (앱의 RoadIndex가 같은 순서로 읽는다)

    "NFRD" 1(형식 번호)
    updatedAt 길이 + UTF-8      (parking-info.json의 updatedAt과 같아야 앱이 쓴다)
    조각 수
      조각마다: 도로 번호, 점 수
    점들: 앞 점과의 차이 (위도, 경도, 1e-5도 정수, zigzag)
    CCTV 수, CCTV마다 도로 번호 + 1 (0: 붙은 도로 없음)
    카메라 수, 카메라마다 도로 번호 + 1
    숫자는 모두 varint
    """
    out = bytearray(b"NFRD")
    out.append(1)
    label = updated_at.encode()
    _varint(len(label), out)
    out += label
    _varint(len(roads["lengths"]), out)
    for group, length in zip(roads["groups"], roads["lengths"]):
        _varint(group, out)
        _varint(length, out)
    for value in roads["coords"]:
        _varint(_zigzag(value), out)
    for values in (cctv_roads, camera_roads):
        _varint(len(values), out)
        for value in values:
            _varint(value + 1, out)
    return bytes(out)
