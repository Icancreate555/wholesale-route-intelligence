
import os
import math
import sqlite3
import uuid
from datetime import datetime, timezone

import pandas as pd
import pydeck as pdk
import streamlit as st

from streamlit_autorefresh import st_autorefresh
from streamlit_js_eval import get_geolocation


# ============================================================
# APP SETTINGS
# ============================================================

APP_TITLE = "Wholesale Route Intelligence"

DB_FILE = "route_intelligence.db"

# How often the browser asks for another GPS position.
GPS_REFRESH_MS = 15_000

# Ignore extremely small GPS movements.
# This reduces noisy points when the phone is stationary.
MIN_POINT_DISTANCE_METERS = 10


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🗺️",
    layout="wide",
)


# ============================================================
# BASIC STYLING
# ============================================================

st.markdown(
    """
    <style>
        .main-title {
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.2rem;
        }

        .subtitle {
            color: #666;
            margin-bottom: 1.5rem;
        }

        .status-card {
            padding: 18px;
            border-radius: 12px;
            border: 1px solid #ddd;
            background: #fafafa;
        }

        .active-card {
            padding: 18px;
            border-radius: 12px;
            border: 1px solid #b7dfc4;
            background: #f3fbf5;
        }

        .warning-card {
            padding: 18px;
            border-radius: 12px;
            border: 1px solid #f0d58c;
            background: #fffaf0;
        }

        .small-note {
            color: #666;
            font-size: 0.85rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# DATABASE
# ============================================================

def get_connection():
    """
    Open the SQLite database.

    SQLite is deliberately used for V1 because it is simple,
    requires no separate server, and keeps the prototype easy
    to understand.
    """
    connection = sqlite3.connect(
        DB_FILE,
        check_same_thread=False,
    )

    connection.row_factory = sqlite3.Row

    return connection


def init_database():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS routes (
            route_id TEXT PRIMARY KEY,
            salesperson TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS route_points (
            point_id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            accuracy REAL,
            FOREIGN KEY(route_id) REFERENCES routes(route_id)
        )
        """
    )

    connection.commit()
    connection.close()


init_database()


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_active_route(salesperson):
    connection = get_connection()

    row = connection.execute(
        """
        SELECT *
        FROM routes
        WHERE salesperson = ?
        AND status = 'active'
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (salesperson,),
    ).fetchone()

    connection.close()

    return row


def get_all_active_routes():
    connection = get_connection()

    rows = connection.execute(
        """
        SELECT *
        FROM routes
        WHERE status = 'active'
        ORDER BY started_at DESC
        """
    ).fetchall()

    connection.close()

    return rows


def get_completed_routes():
    connection = get_connection()

    rows = connection.execute(
        """
        SELECT *
        FROM routes
        WHERE status = 'completed'
        ORDER BY started_at DESC
        """
    ).fetchall()

    connection.close()

    return rows


def create_route(salesperson):
    route_id = str(uuid.uuid4())

    started_at = datetime.now(timezone.utc).isoformat()

    connection = get_connection()

    connection.execute(
        """
        INSERT INTO routes (
            route_id,
            salesperson,
            started_at,
            ended_at,
            status
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            route_id,
            salesperson,
            started_at,
            None,
            "active",
        ),
    )

    connection.commit()
    connection.close()

    return route_id


def end_route(route_id):
    ended_at = datetime.now(timezone.utc).isoformat()

    connection = get_connection()

    connection.execute(
        """
        UPDATE routes
        SET ended_at = ?,
            status = 'completed'
        WHERE route_id = ?
        """,
        (
            ended_at,
            route_id,
        ),
    )

    connection.commit()
    connection.close()


def add_route_point(
    route_id,
    latitude,
    longitude,
    accuracy,
    recorded_at=None,
):
    if recorded_at is None:
        recorded_at = datetime.now(timezone.utc).isoformat()

    connection = get_connection()

    connection.execute(
        """
        INSERT INTO route_points (
            route_id,
            recorded_at,
            latitude,
            longitude,
            accuracy
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            route_id,
            recorded_at,
            latitude,
            longitude,
            accuracy,
        ),
    )

    connection.commit()
    connection.close()


def get_route_points(route_id):
    connection = get_connection()

    rows = connection.execute(
        """
        SELECT *
        FROM route_points
        WHERE route_id = ?
        ORDER BY recorded_at ASC
        """,
        (route_id,),
    ).fetchall()

    connection.close()

    return rows


def get_last_route_point(route_id):
    connection = get_connection()

    row = connection.execute(
        """
        SELECT *
        FROM route_points
        WHERE route_id = ?
        ORDER BY recorded_at DESC
        LIMIT 1
        """,
        (route_id,),
    ).fetchone()

    connection.close()

    return row


# ============================================================
# GEO FUNCTIONS
# ============================================================

def haversine_distance(
    lat1,
    lon1,
    lat2,
    lon2,
):
    """
    Calculate distance between two GPS coordinates in metres.
    """

    earth_radius = 6_371_000

    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_lat / 2) ** 2
        +
        math.cos(lat1)
        *
        math.cos(lat2)
        *
        math.sin(delta_lon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )

    return earth_radius * c


def extract_location(location):
    """
    Convert the result from streamlit-js-eval into
    simple latitude/longitude/accuracy values.
    """

    if not location:
        return None

    if "error" in location:
        return {
            "error": location["error"]
        }

    coords = location.get("coords")

    if not coords:
        return None

    latitude = coords.get("latitude")
    longitude = coords.get("longitude")
    accuracy = coords.get("accuracy")

    if latitude is None or longitude is None:
        return None

    timestamp = location.get("timestamp")

    if timestamp:
        try:
            recorded_at = datetime.fromtimestamp(
                timestamp / 1000,
                tz=timezone.utc,
            ).isoformat()
        except Exception:
            recorded_at = datetime.now(timezone.utc).isoformat()
    else:
        recorded_at = datetime.now(timezone.utc).isoformat()

    return {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "accuracy": float(accuracy) if accuracy is not None else None,
        "recorded_at": recorded_at,
    }


# ============================================================
# MAP PREPARATION
# ============================================================

def build_route_map(active_routes, completed_routes):
    """
    Build a PyDeck map containing:
    - completed routes
    - active routes
    - current positions
    """

    path_records = []
    current_positions = []

    # --------------------------------------------------------
    # ACTIVE ROUTES
    # --------------------------------------------------------

    for route in active_routes:
        points = get_route_points(route["route_id"])

        if not points:
            continue

        path = [
            [
                float(point["longitude"]),
                float(point["latitude"]),
            ]
            for point in points
        ]

        path_records.append(
            {
                "route_id": route["route_id"],
                "salesperson": route["salesperson"],
                "path": path,
                "route_type": "Active",
            }
        )

        latest = points[-1]

        current_positions.append(
            {
                "route_id": route["route_id"],
                "salesperson": route["salesperson"],
                "longitude": float(latest["longitude"]),
                "latitude": float(latest["latitude"]),
            }
        )

    # --------------------------------------------------------
    # COMPLETED ROUTES
    # --------------------------------------------------------

    for route in completed_routes:
        points = get_route_points(route["route_id"])

        if not points:
            continue

        path = [
            [
                float(point["longitude"]),
                float(point["latitude"]),
            ]
            for point in points
        ]

        path_records.append(
            {
                "route_id": route["route_id"],
                "salesperson": route["salesperson"],
                "path": path,
                "route_type": "Completed",
            }
        )

    if not path_records:
        return None

    # --------------------------------------------------------
    # MAP CENTER
    # --------------------------------------------------------

    all_points = []

    for record in path_records:
        all_points.extend(record["path"])

    if all_points:
        center_lon = sum(
            point[0] for point in all_points
        ) / len(all_points)

        center_lat = sum(
            point[1] for point in all_points
        ) / len(all_points)

    else:
        # Kenya fallback
        center_lon = 37.9
        center_lat = -0.3

    path_df = pd.DataFrame(path_records)

    layers = []

    # --------------------------------------------------------
    # ROUTE PATHS
    # --------------------------------------------------------

    layers.append(
        pdk.Layer(
            "PathLayer",
            data=path_df,
            get_path="path",
            get_width=5,
            width_min_pixels=3,
            pickable=True,
            get_color=[
                40,
                120,
                220,
            ],
        )
    )

    # --------------------------------------------------------
    # CURRENT ACTIVE LOCATIONS
    # --------------------------------------------------------

    if current_positions:
        current_df = pd.DataFrame(
            current_positions
        )

        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=current_df,
                get_position=[
                    "longitude",
                    "latitude",
                ],
                get_radius=100,
                radius_min_pixels=7,
                radius_max_pixels=14,
                pickable=True,
                get_fill_color=[
                    220,
                    50,
                    50,
                ],
            )
        )

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=11,
        pitch=0,
    )

    return pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        tooltip={
            "html": """
                <b>{salesperson}</b><br/>
                Route: {route_id}<br/>
                Type: {route_type}
            """
        },
        map_style="light",
    )


# ============================================================
# HEADER
# ============================================================

st.markdown(
    '<div class="main-title">🗺️ Wholesale Route Intelligence</div>',
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="subtitle">
        See where your sales team is actually moving and the areas
        the business is covering.
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.title("Route Intelligence")

role = st.sidebar.radio(
    "Open as",
    [
        "Salesperson",
        "Owner Dashboard",
    ],
)

st.sidebar.markdown("---")

st.sidebar.caption(
    """
    V1 focuses only on movement geography.

    It does not measure time spent with customers.
    """
)


# ============================================================
# GET LOCATION
# ============================================================

# IMPORTANT:
# We call the geolocation component on every rerun rather than
# only inside the active-route branch. This avoids known issues
# with components being called conditionally.
location = get_geolocation()


# ============================================================
# SALESPERSON VIEW
# ============================================================

if role == "Salesperson":

    st.header("Salesperson Route")

    salesperson = st.text_input(
        "Salesperson name",
        placeholder="e.g. Peter",
    ).strip()

    if not salesperson:
        st.info(
            "Enter your name to start or manage a route."
        )

    else:

        active_route = get_active_route(
            salesperson
        )

        # ----------------------------------------------------
        # AUTORERESH WHILE ACTIVE
        # ----------------------------------------------------

        if active_route:

            st_autorefresh(
                interval=GPS_REFRESH_MS,
                key=f"gps_refresh_{active_route['route_id']}",
            )

        # ----------------------------------------------------
        # START ROUTE
        # ----------------------------------------------------

        if active_route:

            st.markdown(
                """
                <div class="active-card">
                    <b>🟢 Route is active</b><br/>
                    Your movement is currently being recorded.
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.write("")

            route_points = get_route_points(
                active_route["route_id"]
            )

            col1, col2, col3 = st.columns(3)

            col1.metric(
                "Route points",
                len(route_points),
            )

            if route_points:

                latest = route_points[-1]

                col2.metric(
                    "Latitude",
                    f"{latest['latitude']:.5f}",
                )

                col3.metric(
                    "Longitude",
                    f"{latest['longitude']:.5f}",
                )

            else:

                col2.metric(
                    "Latitude",
                    "Waiting...",
                )

                col3.metric(
                    "Longitude",
                    "Waiting...",
                )

            st.write("")

            if st.button(
                "⛔ End Route",
                type="primary",
                use_container_width=True,
            ):

                end_route(
                    active_route["route_id"]
                )

                st.success(
                    "Route ended successfully."
                )

                st.rerun()

            # ------------------------------------------------
            # RECORD GPS POINT
            # ------------------------------------------------

            location_data = extract_location(
                location
            )

            if location_data:

                if "error" in location_data:

                    error = location_data["error"]

                    st.error(
                        f"GPS error: {error.get('message', 'Unknown location error')}"
                    )

                else:

                    new_lat = location_data["latitude"]
                    new_lon = location_data["longitude"]
                    accuracy = location_data["accuracy"]
                    recorded_at = location_data["recorded_at"]

                    last_point = get_last_route_point(
                        active_route["route_id"]
                    )

                    should_save = True

                    if last_point:

                        distance = haversine_distance(
                            float(last_point["latitude"]),
                            float(last_point["longitude"]),
                            new_lat,
                            new_lon,
                        )

                        if distance < MIN_POINT_DISTANCE_METERS:
                            should_save = False

                    if should_save:

                        add_route_point(
                            route_id=active_route["route_id"],
                            latitude=new_lat,
                            longitude=new_lon,
                            accuracy=accuracy,
                            recorded_at=recorded_at,
                        )

                        st.caption(
                            f"GPS point recorded • accuracy approximately "
                            f"{accuracy:.0f} m"
                            if accuracy is not None
                            else "GPS point recorded"
                        )

            elif location is None:

                st.warning(
                    "Waiting for GPS permission/location. "
                    "Allow location access in your browser."
                )

        else:

            st.markdown(
                """
                <div class="status-card">
                    <b>Route not active</b><br/>
                    Start a route when you begin field movement.
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.write("")

            if st.button(
                "▶️ Start Route",
                type="primary",
                use_container_width=True,
            ):

                location_data = extract_location(
                    location
                )

                if not location_data:

                    st.error(
                        "We need your current location before starting the route. "
                        "Please allow GPS/location access and try again."
                    )

                elif "error" in location_data:

                    error = location_data["error"]

                    st.error(
                        f"Location error: "
                        f"{error.get('message', 'Unknown error')}"
                    )

                else:

                    route_id = create_route(
                        salesperson
                    )

                    add_route_point(
                        route_id=route_id,
                        latitude=location_data["latitude"],
                        longitude=location_data["longitude"],
                        accuracy=location_data["accuracy"],
                        recorded_at=location_data["recorded_at"],
                    )

                    st.success(
                        "Route started. GPS movement recording is now active."
                    )

                    st.rerun()

        # ----------------------------------------------------
        # SALESPERSON PRIVACY NOTE
        # ----------------------------------------------------

        st.markdown("---")

        st.caption(
            """
            Location recording is active only during a route that
            the salesperson has started. Ending the route stops new
            route points from being recorded.
            """
        )


# ============================================================
# OWNER DASHBOARD
# ============================================================

else:

    st.header("Owner Dashboard")

    active_routes = get_all_active_routes()

    completed_routes = get_completed_routes()

    # --------------------------------------------------------
    # AUTO REFRESH OWNER DASHBOARD
    # --------------------------------------------------------

    if active_routes:

        st_autorefresh(
            interval=10_000,
            key="owner_dashboard_refresh",
        )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Active Routes",
        len(active_routes),
    )

    col2.metric(
        "Completed Routes",
        len(completed_routes),
    )

    total_points = 0

    for route in completed_routes:
        total_points += len(
            get_route_points(
                route["route_id"]
            )
        )

    for route in active_routes:
        total_points += len(
            get_route_points(
                route["route_id"]
            )
        )

    col3.metric(
        "GPS Points",
        total_points,
    )

    st.write("")

    # --------------------------------------------------------
    # LIVE STATUS
    # --------------------------------------------------------

    if active_routes:

        st.subheader("🟢 Live Movement")

        active_data = []

        for route in active_routes:

            points = get_route_points(
                route["route_id"]
            )

            latest = (
                points[-1]
                if points
                else None
            )

            active_data.append(
                {
                    "Salesperson": route["salesperson"],
                    "Started": route["started_at"],
                    "GPS Points": len(points),
                    "Latitude": (
                        round(
                            float(latest["latitude"]),
                            5,
                        )
                        if latest
                        else None
                    ),
                    "Longitude": (
                        round(
                            float(latest["longitude"]),
                            5,
                        )
                        if latest
                        else None
                    ),
                }
            )

        st.dataframe(
            pd.DataFrame(active_data),
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "No salesperson currently has an active route."
        )

    # --------------------------------------------------------
    # MAP
    # --------------------------------------------------------

    st.subheader("Route Map")

    map_data = build_route_map(
        active_routes=active_routes,
        completed_routes=completed_routes[:20],
    )

    if map_data:

        st.pydeck_chart(
            map_data,
            use_container_width=True,
        )

        st.caption(
            "Red points represent the latest recorded position "
            "of active routes. Lines show recorded movement paths."
        )

    else:

        st.info(
            "The map will appear after the first route records GPS points."
        )

    # --------------------------------------------------------
    # COMPLETED ROUTES
    # --------------------------------------------------------

    st.subheader("Completed Routes")

    if completed_routes:

        completed_data = []

        for route in completed_routes:

            points = get_route_points(
                route["route_id"]
            )

            completed_data.append(
                {
                    "Salesperson": route["salesperson"],
                    "Started": route["started_at"],
                    "Ended": route["ended_at"],
                    "GPS Points": len(points),
                    "Route ID": route["route_id"][:8],
                }
            )

        completed_df = pd.DataFrame(
            completed_data
        )

        st.dataframe(
            completed_df,
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "No completed routes yet."
        )

    # --------------------------------------------------------
    # OWNER NOTE
    # --------------------------------------------------------

    st.markdown("---")

    st.caption(
        """
        V1 intentionally focuses on geography:
        where the salesperson moved and which areas were covered.

        Sales, customers, returns, collections, margins and
        cost-to-serve can be connected to these routes in the
        next version.
        """
    )


