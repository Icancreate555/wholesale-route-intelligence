
import math
import sqlite3
import uuid
from datetime import datetime, timezone

import pandas as pd
import pydeck as pdk
import streamlit as st


# ============================================================
# APP CONFIGURATION
# ============================================================

APP_TITLE = "Wholesale Route Intelligence"
DB_FILE = "route_intelligence.db"

# Ignore tiny GPS movements.
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
# DATABASE
# ============================================================

def get_connection():
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
# ROUTE DATABASE FUNCTIONS
# ============================================================

def create_route(salesperson):
    route_id = str(uuid.uuid4())

    started_at = datetime.now(
        timezone.utc
    ).isoformat()

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
    ended_at = datetime.now(
        timezone.utc
    ).isoformat()

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


def get_active_routes():
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


# ============================================================
# GPS DATABASE FUNCTIONS
# ============================================================

def add_route_point(
    route_id,
    latitude,
    longitude,
    accuracy,
    recorded_at,
):
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
# DISTANCE CALCULATION
# ============================================================

def haversine_distance(
    lat1,
    lon1,
    lat2,
    lon2,
):
    earth_radius = 6_371_000

    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_lat / 2) ** 2
        +
        math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )

    return earth_radius * c


# ============================================================
# CONTINUOUS BROWSER GPS COMPONENT
# ============================================================

GPS_HTML = """
<div id="gps-status">
    GPS tracker ready
</div>
"""

GPS_CSS = """
#gps-status {
    font-size: 0.85rem;
    color: var(--st-text-color);
    padding: 4px 0;
}
"""

GPS_JS = """
export default function(component) {

    const {
        data,
        setStateValue,
        parentElement
    } = component;

    // Keep GPS watcher information attached to this
    // component instance so it survives Streamlit reruns.
    if (!parentElement.__routeGps) {
        parentElement.__routeGps = {
            watchId: null,
            tracking: false
        };
    }

    const gps = parentElement.__routeGps;

    const statusElement =
        parentElement.querySelector("#gps-status");


    // --------------------------------------------------------
    // START GPS WATCHING
    // --------------------------------------------------------

    if (data && data.tracking && !gps.tracking) {

        if (!navigator.geolocation) {

            setStateValue(
                "error",
                {
                    code: -1,
                    message:
                        "This browser does not support GPS location."
                }
            );

        } else {

            gps.tracking = true;

            if (statusElement) {
                statusElement.innerText =
                    "🟢 GPS tracking active";
            }


            gps.watchId =
                navigator.geolocation.watchPosition(

                    function(position) {

                        const coords =
                            position.coords;

                        const gpsPoint = {
                            latitude:
                                coords.latitude,

                            longitude:
                                coords.longitude,

                            accuracy:
                                coords.accuracy,

                            altitude:
                                coords.altitude,

                            heading:
                                coords.heading,

                            speed:
                                coords.speed,

                            timestamp:
                                position.timestamp
                        };


                        // Send the newest GPS position
                        // to Streamlit/Python.
                        setStateValue(
                            "position",
                            gpsPoint
                        );
                    },


                    function(error) {

                        setStateValue(
                            "error",
                            {
                                code:
                                    error.code,

                                message:
                                    error.message
                            }
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


    // --------------------------------------------------------
    // STOP GPS WATCHING
    // --------------------------------------------------------

    if (
        data &&
        !data.tracking &&
        gps.tracking
    ) {

        if (gps.watchId !== null) {

            navigator.geolocation.clearWatch(
                gps.watchId
            );

            gps.watchId = null;
        }

        gps.tracking = false;

        if (statusElement) {
            statusElement.innerText =
                "GPS tracker stopped";
        }
    }


    // --------------------------------------------------------
    // CLEAN UP WHEN COMPONENT IS REMOVED
    // --------------------------------------------------------

    return function() {

        if (gps.watchId !== null) {

            navigator.geolocation.clearWatch(
                gps.watchId
            );

            gps.watchId = null;
        }

        gps.tracking = false;
    };
}
"""


gps_component = st.components.v2.component(
    "wholesale_route_gps",
    html=GPS_HTML,
    css=GPS_CSS,
    js=GPS_JS,
)


# ============================================================
# GPS PROCESSING
# ============================================================

def process_gps_position(
    route_id,
    position,
):
    if not position:
        return False

    try:
        latitude = float(
            position["latitude"]
        )

        longitude = float(
            position["longitude"]
        )

        accuracy_value = position.get(
            "accuracy"
        )

        accuracy = (
            float(accuracy_value)
            if accuracy_value is not None
            else None
        )

        timestamp_ms = position.get(
            "timestamp"
        )

        if timestamp_ms:
            recorded_at = (
                datetime.fromtimestamp(
                    timestamp_ms / 1000,
                    tz=timezone.utc,
                ).isoformat()
            )
        else:
            recorded_at = (
                datetime.now(
                    timezone.utc
                ).isoformat()
            )

    except (
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        return False


    # --------------------------------------------------------
    # CHECK LAST POINT
    # --------------------------------------------------------

    last_point = get_last_route_point(
        route_id
    )

    if last_point:

        last_lat = float(
            last_point["latitude"]
        )

        last_lon = float(
            last_point["longitude"]
        )

        distance = haversine_distance(
            last_lat,
            last_lon,
            latitude,
            longitude,
        )

        # Ignore GPS noise / tiny movements.
        if distance < MIN_POINT_DISTANCE_METERS:
            return False


        # Avoid duplicate timestamp.
        if (
            last_point["recorded_at"]
            == recorded_at
        ):
            return False


    # --------------------------------------------------------
    # SAVE GPS POINT
    # --------------------------------------------------------

    add_route_point(
        route_id=route_id,
        latitude=latitude,
        longitude=longitude,
        accuracy=accuracy,
        recorded_at=recorded_at,
    )

    return True


# ============================================================
# MAP
# ============================================================

def create_route_map(
    active_routes,
    completed_routes,
):

    route_paths = []
    current_positions = []

    all_coordinates = []


    # --------------------------------------------------------
    # ACTIVE ROUTES
    # --------------------------------------------------------

    for route in active_routes:

        points = get_route_points(
            route["route_id"]
        )

        if not points:
            continue

        path = []

        for point in points:

            coordinate = [
                float(point["longitude"]),
                float(point["latitude"]),
            ]

            path.append(
                coordinate
            )

            all_coordinates.append(
                coordinate
            )


        if len(path) >= 1:

            route_paths.append(
                {
                    "salesperson":
                        route["salesperson"],

                    "route_type":
                        "Active",

                    "path":
                        path,
                }
            )


        latest = points[-1]

        current_positions.append(
            {
                "salesperson":
                    route["salesperson"],

                "longitude":
                    float(latest["longitude"]),

                "latitude":
                    float(latest["latitude"]),
            }
        )


    # --------------------------------------------------------
    # COMPLETED ROUTES
    # --------------------------------------------------------

    for route in completed_routes:

        points = get_route_points(
            route["route_id"]
        )

        if not points:
            continue

        path = []

        for point in points:

            coordinate = [
                float(point["longitude"]),
                float(point["latitude"]),
            ]

            path.append(
                coordinate
            )

            all_coordinates.append(
                coordinate
            )


        if len(path) >= 1:

            route_paths.append(
                {
                    "salesperson":
                        route["salesperson"],

                    "route_type":
                        "Completed",

                    "path":
                        path,
                }
            )


    # --------------------------------------------------------
    # NO GPS DATA
    # --------------------------------------------------------

    if not all_coordinates:

        return None


    # --------------------------------------------------------
    # MAP CENTER
    # --------------------------------------------------------

    center_lon = sum(
        coordinate[0]
        for coordinate in all_coordinates
    ) / len(all_coordinates)

    center_lat = sum(
        coordinate[1]
        for coordinate in all_coordinates
    ) / len(all_coordinates)


    # --------------------------------------------------------
    # LAYERS
    # --------------------------------------------------------

    layers = []


    if route_paths:

        route_df = pd.DataFrame(
            route_paths
        )

        layers.append(
            pdk.Layer(
                "PathLayer",
                data=route_df,
                get_path="path",
                get_width=6,
                width_min_pixels=4,
                pickable=True,
                get_color=[
                    30,
                    120,
                    220,
                ],
            )
        )


    if current_positions:

        position_df = pd.DataFrame(
            current_positions
        )

        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=position_df,
                get_position=[
                    "longitude",
                    "latitude",
                ],
                get_radius=80,
                radius_min_pixels=8,
                radius_max_pixels=16,
                pickable=True,
                get_fill_color=[
                    220,
                    50,
                    50,
                ],
            )
        )


    # --------------------------------------------------------
    # VIEW
    # --------------------------------------------------------

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=13,
        pitch=0,
    )


    return pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        tooltip={
            "html":
                """
                <b>{salesperson}</b><br/>
                {route_type}
                """
        },
        map_style="light",
    )


# ============================================================
# HEADER
# ============================================================

st.markdown(
    "# 🗺️ Wholesale Route Intelligence"
)

st.caption(
    "See where the business physically moves "
    "and which areas are being covered."
)


# ============================================================
# SIDEBAR
# ============================================================

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
    V1 focuses only on geography.

    It records movement while a salesperson
    has an active route.

    It does not measure time spent with customers.
    """
)


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
            "Enter the salesperson name."
        )

        # Keep component mounted even before
        # a route exists.
        gps_result = gps_component(
            data={
                "tracking": False
            },
            default={
                "position": None,
                "error": None,
            },
            key="gps_tracker",
            on_position_change=lambda: None,
            on_error_change=lambda: None,
        )


    else:

        active_route = get_active_route(
            salesperson
        )

        is_tracking = (
            active_route is not None
        )


        # ----------------------------------------------------
        # MOUNT CONTINUOUS GPS TRACKER
        # ----------------------------------------------------

        gps_result = gps_component(
            data={
                "tracking": is_tracking
            },
            default={
                "position": None,
                "error": None,
            },
            key="gps_tracker",
            on_position_change=lambda: None,
            on_error_change=lambda: None,
        )


        # ----------------------------------------------------
        # SAVE NEW GPS POSITION
        # ----------------------------------------------------

        if (
            active_route
            and gps_result.position
        ):

            process_gps_position(
                active_route["route_id"],
                gps_result.position,
            )


        # ----------------------------------------------------
        # GPS ERROR
        # ----------------------------------------------------

        if (
            active_route
            and gps_result.error
        ):

            error_message = (
                gps_result.error.get(
                    "message",
                    "Unknown GPS error"
                )
            )

            st.error(
                f"GPS error: {error_message}"
            )


        # ----------------------------------------------------
        # ACTIVE ROUTE
        # ----------------------------------------------------

        if active_route:

            st.success(
                "🟢 Route is active — GPS movement is being recorded."
            )

            points = get_route_points(
                active_route["route_id"]
            )


            col1, col2, col3 = st.columns(3)


            col1.metric(
                "GPS Points",
                len(points),
            )


            if points:

                latest = points[-1]

                col2.metric(
                    "Latitude",
                    f"{float(latest['latitude']):.5f}",
                )

                col3.metric(
                    "Longitude",
                    f"{float(latest['longitude']):.5f}",
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


        # ----------------------------------------------------
        # NO ACTIVE ROUTE
        # ----------------------------------------------------

        else:

            st.info(
                "No route is currently active."
            )


            if st.button(
                "▶️ Start Route",
                type="primary",
                use_container_width=True,
            ):

                route_id = create_route(
                    salesperson
                )

                st.success(
                    "Route started. Allow location access if your browser asks."
                )

                st.rerun()


        # ----------------------------------------------------
        # PRIVACY / CONTROL NOTE
        # ----------------------------------------------------

        st.markdown("---")

        st.caption(
            """
            GPS recording only runs while the salesperson has
            an active route. Ending the route stops GPS recording.
            """
        )


# ============================================================
# OWNER DASHBOARD
# ============================================================

else:

    st.header("Owner Dashboard")


    # --------------------------------------------------------
    # LIVE DASHBOARD FRAGMENT
    # --------------------------------------------------------

    @st.fragment(run_every="5s")
    def owner_live_dashboard():

        active_routes = get_active_routes()

        completed_routes = (
            get_completed_routes()
        )


        # ----------------------------------------------------
        # SUMMARY
        # ----------------------------------------------------

        total_points = 0

        for route in active_routes:

            total_points += len(
                get_route_points(
                    route["route_id"]
                )
            )

        for route in completed_routes:

            total_points += len(
                get_route_points(
                    route["route_id"]
                )
            )


        col1, col2, col3 = st.columns(3)


        col1.metric(
            "Active Routes",
            len(active_routes),
        )

        col2.metric(
            "Completed Routes",
            len(completed_routes),
        )

        col3.metric(
            "GPS Points",
            total_points,
        )


        st.write("")


        # ----------------------------------------------------
        # ACTIVE ROUTES
        # ----------------------------------------------------

        st.subheader(
            "🟢 Active Movement"
        )


        if active_routes:

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
                        "Salesperson":
                            route["salesperson"],

                        "Started":
                            route["started_at"],

                        "GPS Points":
                            len(points),

                        "Latitude":
                            (
                                round(
                                    float(
                                        latest[
                                            "latitude"
                                        ]
                                    ),
                                    5,
                                )
                                if latest
                                else None
                            ),

                        "Longitude":
                            (
                                round(
                                    float(
                                        latest[
                                            "longitude"
                                        ]
                                    ),
                                    5,
                                )
                                if latest
                                else None
                            ),
                    }
                )


            st.dataframe(
                pd.DataFrame(
                    active_data
                ),
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.info(
                "No salesperson currently has an active route."
            )


        # ----------------------------------------------------
        # MAP
        # ----------------------------------------------------

        st.subheader(
            "Route Map"
        )


        map_deck = create_route_map(
            active_routes=active_routes,
            completed_routes=completed_routes,
        )


        if map_deck:

            st.pydeck_chart(
                map_deck,
                use_container_width=True,
            )

            st.caption(
                "Blue lines show recorded movement. "
                "Red points show the latest position of an active route."
            )

        else:

            st.info(
                "No GPS route has been recorded yet."
            )


        # ----------------------------------------------------
        # COMPLETED ROUTES
        # ----------------------------------------------------

        st.subheader(
            "Completed Routes"
        )


        if completed_routes:

            completed_data = []


            for route in completed_routes:

                points = get_route_points(
                    route["route_id"]
                )


                completed_data.append(
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
                            route["route_id"][
                                :8
                            ],
                    }
                )


            st.dataframe(
                pd.DataFrame(
                    completed_data
                ),
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.info(
                "No completed routes yet."
            )


    owner_live_dashboard()


    # --------------------------------------------------------
    # V1 SCOPE
    # --------------------------------------------------------

    st.markdown("---")

    st.caption(
        """
        V1 focuses on geography: where the salesperson moved
        and which areas the business physically travelled through.

        Sales, customers, returns, collections, margins and
        cost-to-serve will be connected to these routes later.
        """
    )
```
