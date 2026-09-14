import math
import sqlite3
import uuid
from datetime import datetime, timezone

import pandas as pd
import pydeck as pdk
import streamlit as st


# ============================================================
# CONFIG
# ============================================================

DB_FILE = "route_intelligence.db"
MIN_DISTANCE_METERS = 10


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="Wholesale Route Intelligence",
    page_icon="🗺️",
    layout="wide",
)


# ============================================================
# DATABASE
# ============================================================

def db():
    con = sqlite3.connect(DB_FILE, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()

    con.execute("""
        CREATE TABLE IF NOT EXISTS routes (
            route_id TEXT PRIMARY KEY,
            salesperson TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS route_points (
            point_id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            accuracy REAL
        )
    """)

    con.commit()
    con.close()


init_db()


# ============================================================
# ROUTES
# ============================================================

def start_route(name):
    route_id = str(uuid.uuid4())

    con = db()
    con.execute(
        """
        INSERT INTO routes
        (route_id, salesperson, started_at, status)
        VALUES (?, ?, ?, ?)
        """,
        (
            route_id,
            name,
            datetime.now(timezone.utc).isoformat(),
            "active",
        ),
    )
    con.commit()
    con.close()

    return route_id


def finish_route(route_id):
    con = db()

    con.execute(
        """
        UPDATE routes
        SET status = 'completed',
            ended_at = ?
        WHERE route_id = ?
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            route_id,
        ),
    )

    con.commit()
    con.close()


def active_route(name):
    con = db()

    row = con.execute(
        """
        SELECT *
        FROM routes
        WHERE salesperson = ?
        AND status = 'active'
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (name,),
    ).fetchone()

    con.close()
    return row


def all_active_routes():
    con = db()

    rows = con.execute(
        """
        SELECT *
        FROM routes
        WHERE status = 'active'
        ORDER BY started_at DESC
        """
    ).fetchall()

    con.close()
    return rows


def completed_routes():
    con = db()

    rows = con.execute(
        """
        SELECT *
        FROM routes
        WHERE status = 'completed'
        ORDER BY started_at DESC
        """
    ).fetchall()

    con.close()
    return rows


# ============================================================
# GPS
# ============================================================

def route_points(route_id):
    con = db()

    rows = con.execute(
        """
        SELECT *
        FROM route_points
        WHERE route_id = ?
        ORDER BY recorded_at
        """,
        (route_id,),
    ).fetchall()

    con.close()
    return rows


def last_point(route_id):
    con = db()

    row = con.execute(
        """
        SELECT *
        FROM route_points
        WHERE route_id = ?
        ORDER BY recorded_at DESC
        LIMIT 1
        """,
        (route_id,),
    ).fetchone()

    con.close()
    return row


def save_point(route_id, lat, lon, accuracy, timestamp):
    previous = last_point(route_id)

    if previous:
        distance = haversine(
            previous["latitude"],
            previous["longitude"],
            lat,
            lon,
        )

        if distance < MIN_DISTANCE_METERS:
            return False

    con = db()

    con.execute(
        """
        INSERT INTO route_points
        (route_id, recorded_at, latitude, longitude, accuracy)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            route_id,
            timestamp,
            lat,
            lon,
            accuracy,
        ),
    )

    con.commit()
    con.close()

    return True


def haversine(lat1, lon1, lat2, lon2):
    radius = 6371000

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)

    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1)
        * math.cos(p2)
        * math.sin(dl / 2) ** 2
    )

    return radius * 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )


# ============================================================
# BROWSER GPS COMPONENT
# ============================================================

GPS_COMPONENT = st.components.v2.component(
    "route_gps_tracker",

    html="""
        <div id="gps">
            GPS: waiting
        </div>
    """,

    css="""
        #gps {
            font-size: 14px;
            padding: 5px 0;
        }
    """,

    js="""
        export default function(component) {

            const {
                data,
                parentElement,
                setStateValue
            } = component;

            const box =
                parentElement.querySelector("#gps");

            if (!parentElement.__gps) {

                parentElement.__gps = {
                    watchId: null,
                    active: false
                };
            }

            const gps = parentElement.__gps;


            // START WATCHING
            if (
                data.tracking &&
                !gps.active
            ) {

                if (!navigator.geolocation) {

                    box.innerText =
                        "GPS not supported";

                    setStateValue(
                        "error",
                        "Browser does not support geolocation"
                    );

                } else {

                    gps.active = true;

                    box.innerText =
                        "🟢 GPS tracking active";

                    gps.watchId =
                        navigator.geolocation.watchPosition(

                            function(position) {

                                const c =
                                    position.coords;

                                setStateValue(
                                    "position",
                                    {
                                        latitude:
                                            c.latitude,

                                        longitude:
                                            c.longitude,

                                        accuracy:
                                            c.accuracy,

                                        timestamp:
                                            position.timestamp
                                    }
                                );

                                box.innerText =
                                    "🟢 GPS point received";
                            },

                            function(error) {

                                box.innerText =
                                    "🔴 GPS error";

                                setStateValue(
                                    "error",
                                    error.message
                                );
                            },

                            {
                                enableHighAccuracy: true,
                                maximumAge: 5000,
                                timeout: 15000
                            }
                        );
                }
            }


            // STOP WATCHING
            if (
                !data.tracking &&
                gps.active
            ) {

                if (
                    gps.watchId !== null
                ) {

                    navigator.geolocation.clearWatch(
                        gps.watchId
                    );
                }

                gps.watchId = null;
                gps.active = false;

                box.innerText =
                    "GPS stopped";
            }


            // CLEANUP
            return function() {

                if (
                    gps.watchId !== null
                ) {

                    navigator.geolocation.clearWatch(
                        gps.watchId
                    );
                }

                gps.watchId = null;
                gps.active = false;
            };
        }
    """,
)


# ============================================================
# MAP
# ============================================================

def make_map(routes):
    paths = []
    positions = []
    coordinates = []

    for route in routes:

        points = route_points(
            route["route_id"]
        )

        if not points:
            continue

        path = []

        for point in points:

            coord = [
                float(point["longitude"]),
                float(point["latitude"]),
            ]

            path.append(coord)
            coordinates.append(coord)

        paths.append(
            {
                "salesperson": route["salesperson"],
                "path": path,
            }
        )

        if route["status"] == "active":

            latest = points[-1]

            positions.append(
                {
                    "salesperson":
                        route["salesperson"],

                    "longitude":
                        float(latest["longitude"]),

                    "latitude":
                        float(latest["latitude"]),
                }
            )

    if not coordinates:
        return None

    center_lon = sum(
        x[0] for x in coordinates
    ) / len(coordinates)

    center_lat = sum(
        x[1] for x in coordinates
    ) / len(coordinates)

    layers = []

    if paths:

        layers.append(
            pdk.Layer(
                "PathLayer",
                data=pd.DataFrame(paths),
                get_path="path",
                get_width=6,
                width_min_pixels=4,
                pickable=True,
                get_color=[30, 120, 220],
            )
        )

    if positions:

        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=pd.DataFrame(positions),
                get_position=[
                    "longitude",
                    "latitude",
                ],
                get_radius=80,
                radius_min_pixels=8,
                pickable=True,
                get_fill_color=[220, 50, 50],
            )
        )

    return pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(
            latitude=center_lat,
            longitude=center_lon,
            zoom=13,
        ),
        tooltip={
            "html":
                "<b>{salesperson}</b>"
        },
        map_style="light",
    )


# ============================================================
# HEADER
# ============================================================

st.title("🗺️ Wholesale Route Intelligence")

st.caption(
    "V1: capture where the salesperson physically moves."
)


# ============================================================
# MODE
# ============================================================

mode = st.sidebar.radio(
    "Open as",
    [
        "Salesperson",
        "Owner Dashboard",
    ],
)


# ============================================================
# SALESPERSON
# ============================================================

if mode == "Salesperson":

    st.header("Salesperson Route")

    name = st.text_input(
        "Salesperson name",
        placeholder="e.g. Peter",
    ).strip()

    if not name:

        st.info(
            "Enter your name to begin."
        )

    else:

        route = active_route(name)

        tracking = route is not None

        gps = GPS_COMPONENT(
            data={
                "tracking": tracking
            },
            default={
                "position": None,
                "error": None,
            },
            key="gps",
            on_position_change=lambda: None,
            on_error_change=lambda: None,
        )

        # ----------------------------------------------------
        # SAVE GPS POSITION
        # ----------------------------------------------------

        if (
            route
            and gps.position
        ):

            position = gps.position

            timestamp = datetime.fromtimestamp(
                position["timestamp"] / 1000,
                tz=timezone.utc,
            ).isoformat()

            save_point(
                route["route_id"],
                float(position["latitude"]),
                float(position["longitude"]),
                float(position["accuracy"]),
                timestamp,
            )

        # ----------------------------------------------------
        # GPS DIAGNOSTICS
        # ----------------------------------------------------

        with st.expander(
            "GPS diagnostics",
            expanded=True,
        ):

            if gps.position:

                st.success(
                    "GPS position received"
                )

                st.write(
                    "Latitude:",
                    gps.position["latitude"],
                )

                st.write(
                    "Longitude:",
                    gps.position["longitude"],
                )

                st.write(
                    "Accuracy:",
                    f"{gps.position['accuracy']:.1f} m",
                )

            elif gps.error:

                st.error(
                    f"GPS error: {gps.error}"
                )

            else:

                st.info(
                    "Waiting for GPS position..."
                )

        # ----------------------------------------------------
        # ACTIVE ROUTE
        # ----------------------------------------------------

        if route:

            points = route_points(
                route["route_id"]
            )

            st.success(
                "🟢 Route is active"
            )

            st.metric(
                "GPS Points recorded",
                len(points),
            )

            if st.button(
                "⛔ End Route",
                type="primary",
                use_container_width=True,
            ):

                finish_route(
                    route["route_id"]
                )

                st.success(
                    "Route ended."
                )

                st.rerun()

        # ----------------------------------------------------
        # START ROUTE
        # ----------------------------------------------------

        else:

            if st.button(
                "▶️ Start Route",
                type="primary",
                use_container_width=True,
            ):

                start_route(name)

                st.success(
                    "Route started. Allow location access."
                )

                st.rerun()

    st.markdown("---")

    st.caption(
        "GPS recording occurs only while an active route is running."
    )


# ============================================================
# OWNER DASHBOARD
# ============================================================

else:

    st.header("Owner Dashboard")

    active = all_active_routes()
    completed = completed_routes()

    all_routes = list(active) + list(completed)

    total_points = sum(
        len(route_points(r["route_id"]))
        for r in all_routes
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Active Routes",
        len(active),
    )

    c2.metric(
        "Completed Routes",
        len(completed),
    )

    c3.metric(
        "GPS Points",
        total_points,
    )

    # --------------------------------------------------------
    # MAP
    # --------------------------------------------------------

    st.subheader("Route Map")

    map_object = make_map(
        all_routes
    )

    if map_object:

        st.pydeck_chart(
            map_object,
            use_container_width=True,
        )

    else:

        st.info(
            "No GPS route points have been recorded yet."
        )

    # --------------------------------------------------------
    # ACTIVE ROUTES
    # --------------------------------------------------------

    st.subheader("Active Routes")

    if active:

        rows = []

        for route in active:

            points = route_points(
                route["route_id"]
            )

            latest = (
                points[-1]
                if points
                else None
            )

            rows.append(
                {
                    "Salesperson":
                        route["salesperson"],

                    "Started":
                        route["started_at"],

                    "GPS Points":
                        len(points),

                    "Latitude":
                        (
                            round(
                                latest["latitude"],
                                5,
                            )
                            if latest
                            else None
                        ),

                    "Longitude":
                        (
                            round(
                                latest["longitude"],
                                5,
                            )
                            if latest
                            else None
                        ),
                }
            )

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "No active routes."
        )

    # --------------------------------------------------------
    # COMPLETED ROUTES
    # --------------------------------------------------------

    st.subheader("Completed Routes")

    if completed:

        rows = []

        for route in completed:

            points = route_points(
                route["route_id"]
            )

            rows.append(
                {
                    "Salesperson":
                        route["salesperson"],

                    "Started":
                        route["started_at"],

                    "Ended":
                        route["ended_at"],

                    "GPS Points":
                        len(points),

                    "Route ID":
                        route["route_id"][:8],
                }
            )

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "No completed routes yet."
        )

    st.markdown("---")

    st.caption(
        "V1 focuses on geography: where the salesperson moved "
        "and which areas the business physically travelled through."
    )
