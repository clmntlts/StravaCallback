// Import the 'node-fetch' module for making HTTP requests
import fetch from 'node-fetch';

// Handler function for the API route
export default async function handler(req, res) {
    // Check if the request method is POST
    if (req.method === 'POST') {
        // Extract the code from the request body
        const { code } = req.body;

        // Validate the presence of the code
        if (!code) {
            return res.status(400).json({ success: false, message: 'Authorization code is required' });
        }

        // Get environment variables for Botpress webhook and Strava client details
        const webhookUrl = process.env.BOTPRESS_WEBHOOK_URL;
        const clientId = process.env.STRAVA_CLIENT_ID;
        const clientSecret = process.env.STRAVA_CLIENT_SECRET;

        // Construct the payload for the webhook
        const payload = {
            code,
            client_id: clientId,
            client_secret: clientSecret,
            conversationId: 'conv_01J82FTZNZEP72YQFKANNZNMFK'
        };

        try {
            // Send the payload to the Botpress webhook
            const response = await fetch(webhookUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            // Parse the response from the webhook
            const data = await response.json();

            // Respond with the result of the webhook request
            res.status(200).json({ success: true, data });
        } catch (error) {
            // Log and respond with an error if the webhook request fails
            console.error('Error sending POST request to webhook:', error);
            res.status(500).json({ success: false, message: 'Failed to send POST request to webhook', error });
        }
    } else {
        // Respond with a 405 status code if the method is not allowed
        res.status(405).json({ success: false, message: 'Method not allowed' });
    }
}
