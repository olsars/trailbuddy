import React from "react";
import { MapContainer, TileLayer, Polyline, Marker, Circle } from "react-leaflet";
import L from "leaflet";

function createAvatarIcon(label, avatarUrl, isCurrentUser) {
  return L.divIcon({
    className: "custom-avatar-pin",
    html: `
      <div style="position: relative; display: flex; flex-direction: column; align-items: center;">
        ${
          isCurrentUser
            ? `<div style="
                position: absolute;
                top: -24px;
                background: #1e293b;
                color: #ffffff;
                font-size: 11px;
                font-weight: 600;
                padding: 2px 8px;
                border-radius: 999px;
                white-space: nowrap;
                box-shadow: 0 2px 6px rgba(0,0,0,0.4);
              ">
                <span style="color: #f97316;">●</span> ${label}
              </div>`
            : ""
        }
        <div style="
          width: 40px;
          height: 40px;
          border-radius: 50%;
          border: 3px solid ${isCurrentUser ? "#22c55e" : "#f59e0b"};
          background: #ffffff;
          overflow: hidden;
          box-shadow: 0 4px 10px rgba(0,0,0,0.5);
        ">
          <img src="${avatarUrl}" alt="${label}" style="width: 100%; height: 100%; object-fit: cover;" />
        </div>
        ${
          !isCurrentUser
            ? `<span style="
                color: #ffffff;
                font-size: 12px;
                font-weight: 600;
                margin-top: 4px;
                text-shadow: 0 1px 3px rgba(0,0,0,0.8);
              ">
                ${label}
              </span>`
            : ""
        }
      </div>
    `,
    iconSize: [40, 40],
    iconAnchor: [20, 20],
  });
}

export default function WalkMap({
  routeCoordinates = [],
  markers = [],
  center = [37.9555, -122.5830],
  zoom = 15,
}) {
  const currentUser = markers.find((m) => m.isCurrentUser);

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <MapContainer
        center={center}
        zoom={zoom}
        style={{ width: "100%", height: "100%", background: "#0b132b" }}
        zoomControl={false}
      >
        <TileLayer
          attribution='&copy; <a href="https://carto.com/">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />

        {routeCoordinates.length > 0 && (
          <Polyline
            positions={routeCoordinates}
            pathOptions={{
              color: "#f97316",
              weight: 4,
              dashArray: "8, 8",
              opacity: 0.9,
            }}
          />
        )}

        {currentUser && (
          <Circle
            center={currentUser.position}
            radius={90}
            pathOptions={{
              color: "#f97316",
              fillColor: "#f97316",
              fillOpacity: 0.15,
              weight: 1,
            }}
          />
        )}

        {markers.map((item) => (
          <Marker
            key={item.id}
            position={item.position}
            icon={createAvatarIcon(item.label, item.avatarUrl, item.isCurrentUser)}
          />
        ))}
      </MapContainer>
    </div>
  );
}